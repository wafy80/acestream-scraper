from flask_restx import Namespace, Resource, fields
from app.models import AcestreamChannel, ScrapedURL
from app.utils.config import Config

api = Namespace('stats', description='Application statistics')

url_stats_model = api.model('URLStats', {
    'id': fields.String(description='ID of the URL'),  # Include ID field
    'url': fields.String(description='URL being scraped'),
    'url_type': fields.String(description='Type of URL (regular, zeronet)'),
    'status': fields.String(description='Current status of the URL'),
    'last_processed': fields.DateTime(description='When the URL was last processed'),
    'channel_count': fields.Integer(description='Number of channels from this URL'),
    'enabled': fields.Boolean(description='Whether this URL is enabled'),
    'error_count': fields.Integer(description='Number of consecutive errors'),
    'last_error': fields.String(description='Last error message, if any')
})

stats_model = api.model('Stats', {
    'urls': fields.List(fields.Nested(url_stats_model), description='List of all tracked URLs'),
    'total_channels': fields.Integer(description='Total number of channels'),
    'channels_checked': fields.Integer(description='Number of channels with status checked'),
    'channels_online': fields.Integer(description='Number of online channels'),
    'channels_offline': fields.Integer(description='Number of offline channels'),
    'base_url': fields.String(description='Base URL for playlist generation'),
    'ace_engine_url': fields.String(description='URL of the Acestream Engine'),
    'rescrape_interval': fields.Integer(description='Hours between automatic rescans'),
    'addpid': fields.Boolean(description='Whether to add PID parameter to URLs'),
    'task_manager_status': fields.String(description='Status of the background task manager')
})

@api.route('/')
class Stats(Resource):
    @api.doc('get_stats')
    @api.marshal_with(stats_model)
    def get(self):
        """Get application statistics including URL and channel information."""
        try:
            urls = ScrapedURL.query.all()
            channels = AcestreamChannel.query.all()
            config = Config()
            
            # Calculate channel stats more robustly
            total_channels = len(channels)
            channels_checked = sum(1 for ch in channels if ch.last_checked is not None)
            channels_online = sum(1 for ch in channels if ch.last_checked is not None and ch.is_online is True)
            channels_offline = sum(1 for ch in channels if ch.last_checked is not None and ch.is_online is False)
            
            # Build URL stats
            url_stats = []
            for url in urls:
                channel_count = AcestreamChannel.query.filter_by(source_url=url.url).count()
                
                url_stats.append({
                    'id': url.id,
                    'url': url.url,
                    'url_type': url.url_type,
                    'status': url.status,
                    'last_processed': url.last_processed, 
                    'channel_count': channel_count,
                    'enabled': url.status != 'disabled',
                    'error_count': url.error_count or 0,
                    'last_error': url.last_error
                })
            
            try:
                from app.tasks.manager import task_manager
                task_status = "running" if task_manager and task_manager.running else "stopped"
            except ImportError:
                task_status = "unknown"
            
            return {
                'urls': url_stats,
                'total_channels': total_channels,
                'channels_checked': channels_checked, 
                'channels_online': channels_online,
                'channels_offline': channels_offline,
                'base_url': config.base_url,
                'ace_engine_url': config.ace_engine_url,
                'rescrape_interval': config.rescrape_interval,
                'addpid': config.addpid,
                'task_manager_status': task_status
            }
        except Exception as e:
            api.abort(500, f"Error retrieving statistics: {str(e)}")

@api.route('/tv-channels/')
class TVChannelStats(Resource):
    @api.doc('get_tv_channel_stats')
    def get(self):
        """Get statistics about TV channels"""
        try:
            from app.models.tv_channel import TVChannel
            from sqlalchemy import func
            
            # Get total count
            total_count = TVChannel.query.count()
            
            # Get active count
            active_count = TVChannel.query.filter_by(is_active=True).count()
            
            # Get count with EPG
            with_epg_count = TVChannel.query.filter(TVChannel.epg_id.isnot(None)).count()
            
            # Get total acestreams associated with TV channels
            acestreams_count = AcestreamChannel.query.filter(AcestreamChannel.tv_channel_id.isnot(None)).count()
            
            return {
                'total': total_count,
                'active': active_count,
                'with_epg': with_epg_count,
                'acestreams': acestreams_count
            }
        except Exception as e:
            api.abort(500, f"Error retrieving TV channel statistics: {str(e)}")