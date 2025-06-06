from flask_restx import Namespace, Resource, fields
from flask import request, jsonify
import logging

from app.models.epg_source import EPGSource
from app.models.epg_string_mapping import EPGStringMapping
from app.repositories.epg_source_repository import EPGSourceRepository
from app.repositories.epg_string_mapping_repository import EPGStringMappingRepository
from app.repositories.epg_channel_repository import EPGChannelRepository
from app.services.epg_service import EPGService

logger = logging.getLogger(__name__)

api = Namespace('epg', description='EPG configuration and management')

# Models for API documentation
epg_source_model = api.model('EPGSource', {
    'id': fields.Integer(readonly=True, description='Unique ID for the source'),
    'url': fields.String(required=True, description='URL of the EPG source (XMLTV)'),
    'enabled': fields.Boolean(default=True, description='Whether this source is enabled'),
    'last_updated': fields.DateTime(readonly=True, description='Last update timestamp'),
    'error_count': fields.Integer(readonly=True, description='Error counter'),
    'last_error': fields.String(readonly=True, description='Last error message')
})

epg_string_mapping_model = api.model('EPGStringMapping', {
    'id': fields.Integer(readonly=True, description='Unique ID for the mapping'),
    'search_pattern': fields.String(required=True, description='Text pattern to search in channel names'),
    'epg_channel_id': fields.String(required=True, description='EPG channel ID to map to')
})

# Auto-scan model including threshold and processing options
auto_scan_model = api.model('AutoScan', {
    'threshold': fields.Float(required=False, description='Similarity threshold (0.0-1.0)', default=0.8),
    'clean_unmatched': fields.Boolean(required=False, description='Clean EPG data if no match is found', default=False),
    'respect_existing': fields.Boolean(required=False, description='Don\'t modify channels that already have EPG data', default=False)
})

# Update options model for EPG channel updates
update_channels_model = api.model('UpdateChannels', {
    'respect_existing': fields.Boolean(required=False, description='Don\'t modify channels that already have EPG data', default=False),
    'clean_unmatched': fields.Boolean(required=False, description='Clean EPG data if no match is found', default=False)
})

# Endpoints for EPG sources
@api.route('/sources')
class EPGSourceListResource(Resource):
    @api.marshal_with(epg_source_model)
    def get(self):
        """Get all EPG sources"""
        repo = EPGSourceRepository()
        return repo.get_all()
    
    @api.expect(epg_source_model)
    @api.marshal_with(epg_source_model, code=201)
    def post(self):
        """Add a new EPG source"""
        data = request.json
        repo = EPGSourceRepository()
        
        # Validate URL presence
        url = data.get('url', '').strip()
        if not url:
            api.abort(400, "URL is required")
        
        # Validate URL format
        import re
        url_pattern = re.compile(r'^https?://\S+\.\S+')
        if not url_pattern.match(url):
            api.abort(400, "Invalid URL format. Must start with http:// or https://")
        
        # Check for duplicate sources
        existing_sources = repo.get_all()
        for source in existing_sources:
            if source.url.lower() == url.lower():
                api.abort(409, "This EPG source URL already exists")
        
        # Create new source
        source = EPGSource(
            url=url,
            enabled=data.get('enabled', True)
        )
        
        repo.create(source)
        return source, 201

@api.route('/sources/<int:id>')
class EPGSourceResource(Resource):
    def delete(self, id):
        """Delete EPG source"""
        repo = EPGSourceRepository()
        source = repo.get_by_id(id)
        if not source:
            api.abort(404, f"EPG source with ID {id} not found")
        
        repo.delete(source)
        return {'message': f'EPG source {id} deleted'}, 200

    @api.doc('update_epg_source')
    @api.expect(api.model('EPGSourceUpdate', {
        'enabled': fields.Boolean(required=False, description='Whether this source is enabled')
    }))
    @api.marshal_with(epg_source_model)
    def put(self, id):
        """Update an EPG source's enabled status"""
        repo = EPGSourceRepository()
        source = repo.get_by_id(id)
        if not source:
            api.abort(404, f"EPG source with ID {id} not found")
        
        data = request.json
        
        # Only allow updating the enabled flag
        if 'enabled' in data:
            source.enabled = data['enabled']
            
        repo.update(source)
        return source

# Endpoints for pattern mappings
@api.route('/mappings')
class EPGStringMappingListResource(Resource):
    @api.marshal_list_with(epg_string_mapping_model)
    def get(self):
        """Get all pattern mappings"""
        repo = EPGStringMappingRepository()
        return repo.get_all()
    
    @api.expect(epg_string_mapping_model)
    @api.marshal_with(epg_string_mapping_model, code=201)
    @api.response(409, 'Mapping already exists')
    def post(self):
        """Add a new pattern mapping"""
        data = request.json
        repo = EPGStringMappingRepository()
        
        # Validate required fields
        search_pattern = data.get('search_pattern')
        if not search_pattern:
            api.abort(400, "Search pattern is required")
            
        # Check for duplicate mappings
        existing_mappings = repo.get_all()
        for mapping in existing_mappings:
            if mapping.search_pattern.lower() == search_pattern.lower():
                api.abort(409, "This search pattern already exists")
        
        # Create new mapping from request data
        mapping = EPGStringMapping(
            search_pattern=search_pattern,
            epg_channel_id=data.get('epg_channel_id')
        )
        
        try:
            repo.create(mapping)
            return mapping, 201
        except Exception as e:
            logger.error(f"Error creating EPG mapping: {str(e)}")
            api.abort(500, f"Failed to create mapping: {str(e)}")

@api.route('/mappings/<int:id>')
class EPGStringMappingResource(Resource):
    def delete(self, id):
        """Delete pattern mapping"""
        repo = EPGStringMappingRepository()
        mapping = repo.get_by_id(id)
        if not mapping:
            api.abort(404, f"Mapping with ID {id} not found")
        
        repo.delete(mapping)
        return {'message': f'Mapping {id} deleted'}, 200

# Endpoints for EPG operations
@api.route('/refresh')
class EPGRefreshResource(Resource):
    def post(self):
        """Refresh EPG data from all sources"""
        service = EPGService()
        data = service.fetch_epg_data()
        return {
            'message': 'EPG data refreshed successfully',
            'channels_found': len(data)
        }

@api.route('/update-channels')
class EPGUpdateChannelsResource(Resource):
    @api.doc('update_epg_channels')
    @api.expect(update_channels_model)
    def post(self):
        """Update all channels with EPG metadata"""
        try:
            data = request.get_json() or {}
            respect_existing = data.get('respect_existing', False)
            clean_unmatched = data.get('clean_unmatched', False)
            
            service = EPGService()
            stats = service.update_all_channels_epg(
                respect_existing=respect_existing,
                clean_unmatched=clean_unmatched
            )
            
            return {
                'message': 'Channel EPG update process completed',
                'stats': stats
            }
        except Exception as e:
            logger.error(f"Error updating channels with EPG data: {str(e)}")
            return {'error': str(e)}, 500

@api.route('/channels')
@api.param('search', 'Search term to filter channels')
@api.param('page', 'Page number (default: 1)')
@api.param('per_page', 'Items per page (default: 20)')
class EPGChannelsResource(Resource):
    def get(self):
        """Get all available EPG channel IDs and names"""
        # Get pagination and search parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search_term = request.args.get('search', '')
        
        # Use EPGChannelRepository to get channels from database
        epg_channel_repo = EPGChannelRepository()
        all_channels = epg_channel_repo.get_all()
        
        source_repo = EPGSourceRepository()
        sources = {source.id: source for source in source_repo.get_all()}

        # Sequential numbering of sources for UI display
        source_numbers = {}
        for i, source_id in enumerate(sources.keys()):
            source_numbers[source_id] = f"Source #{i+1}"

        # Filter channels if search term provided
        filtered_channels = []
        for channel in all_channels:
            if not search_term or (
                search_term.lower() in (channel.name or '').lower() or
                search_term.lower() in (channel.channel_xml_id or '').lower()
            ):
                # Get source info for the channel
                source_id = channel.epg_source_id
                source_name = source_numbers.get(source_id, "Unknown") if source_id else ""
                source_url = sources[source_id].url if source_id and source_id in sources else ""
                
                filtered_channels.append({
                    'id': channel.channel_xml_id,
                    'name': channel.name or channel.channel_xml_id,
                    'source_id': source_id,
                    'source_name': source_name,
                    'source_url': source_url,
                    'icon': channel.icon_url,
                    'language': channel.language
                })

        # Calculate pagination
        total_channels = len(filtered_channels)
        total_pages = (total_channels + per_page - 1) // per_page
        
        # Apply pagination
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_channels)
        paginated_channels = filtered_channels[start_idx:end_idx]
        
        # Return with pagination info
        return {
            'channels': paginated_channels,
            'page': page,
            'per_page': per_page,
            'total_channels': total_channels,
            'total_pages': total_pages
        }

@api.route('/auto-scan')
class EPGAutoScanResource(Resource):
    @api.doc('auto_scan_epg')
    @api.expect(auto_scan_model)
    @api.response(200, 'Scan completed')
    def post(self):
        """Scan channels and automatically map EPG data based on name similarity."""
        try:
            data = request.get_json() or {}
            threshold = data.get('threshold', 0.8)
            clean_unmatched = data.get('clean_unmatched', False)
            respect_existing = data.get('respect_existing', False)
            
            # Get all EPG channels from repository
            epg_channel_repo = EPGChannelRepository()
            all_epg_channels = []
            
            # Get all sources
            source_repo = EPGSourceRepository()
            sources = source_repo.get_all()
            
            # Collect channels from all sources
            for source in sources:
                channels = epg_channel_repo.get_by_source_id(source.id)
                
                # Convert to the format expected by the service
                for channel in channels:
                    all_epg_channels.append({
                        'id': channel.channel_xml_id,
                        'name': channel.name,
                        'logo': channel.icon_url,
                        'language': channel.language,
                        'source_id': source.id
                    })
            
            logger.info(f"Found {len(all_epg_channels)} EPG channels in repository")
            
            # Use the existing service for auto-scanning
            service = EPGService()
            result = service.auto_scan_channels(
                threshold=threshold,
                clean_unmatched=clean_unmatched,
                respect_existing=respect_existing,
                epg_channels=all_epg_channels  # Pass the channels from repository
            )
            
            return {
                'message': 'EPG auto-scan completed successfully',
                'total': result.get('total', 0),
                'matched': result.get('matched', 0),
                'cleaned': result.get('cleaned', 0),
                'skipped': result.get('skipped', 0)
            }
        except Exception as e:
            logger.error(f"Error during auto-scan: {str(e)}")
            return {'error': str(e)}, 500

@api.route('/channel/<string:id>')
class EPGChannelResource(Resource):
    @api.doc('get_epg_channel')
    @api.response(200, 'Success')
    @api.response(404, 'EPG channel not found')
    def get(self, id):
        """Get a specific EPG channel by ID"""
        repo = EPGChannelRepository()
        channel = repo.get_by_id(id)
        
        if not channel:
            # If not found in database, try to find in all sources
            epg_service = EPGService()
            for source in EPGSourceRepository().get_all():
                channels = epg_service.get_channels_from_source(source.id)
                for ch in channels:
                    if ch['id'] == id:
                        return {
                            'id': ch['id'],
                            'name': ch['name'],
                            'icon': ch['icon'],
                            'source_id': source.id,
                            'language': ch.get('language')
                        }
            
            api.abort(404, f'EPG channel with ID {id} not found')
        
        return {
            'id': channel.channel_xml_id,
            'name': channel.name,
            'icon': channel.icon_url,
            'source_id': channel.epg_source_id,
            'language': channel.language
        }