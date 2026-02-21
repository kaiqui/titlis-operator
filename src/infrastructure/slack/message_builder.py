"""
Slack message builder for official SDK.
"""
from datetime import datetime
from typing import Dict, Any, List
from src.domain.slack_models import SlackMessageTemplate, NotificationSeverity


class SlackMessageBuilder:
    
    
    @staticmethod
    def create_blocks(
        title: str,
        message: str,
        severity: NotificationSeverity,
        template: SlackMessageTemplate,
        metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        
        metadata = metadata or {}
        blocks = []
        
        # Header with emoji based on severity
        emoji_map = {
            NotificationSeverity.INFO: "ℹ️",
            NotificationSeverity.WARNING: "⚠️",
            NotificationSeverity.ERROR: "❌",
            NotificationSeverity.CRITICAL: "🚨"
        }
        
        emoji = emoji_map.get(severity, "📢")
        
        # Header block
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {title}",
                "emoji": True
            }
        })
        
        # Divider
        blocks.append({"type": "divider"})
        
        # Message block
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message[:template.max_message_length]
            }
        })
        
        # Context block with metadata
        context_elements = []
        
        if template.include_timestamp and metadata.get("timestamp"):
            context_elements.append({
                "type": "mrkdwn",
                "text": f"*Timestamp:* {metadata['timestamp']}"
            })
        
        if template.include_cluster_info and metadata.get("cluster_name"):
            context_elements.append({
                "type": "mrkdwn",
                "text": f"*Cluster:* {metadata['cluster_name']}"
            })
        
        if template.include_namespace and metadata.get("namespace"):
            context_elements.append({
                "type": "mrkdwn",
                "text": f"*Namespace:* {metadata['namespace']}"
            })
        
        if metadata.get("operator"):
            context_elements.append({
                "type": "mrkdwn",
                "text": f"*Operator:* {metadata['operator']}"
            })
        
        if context_elements:
            blocks.append({
                "type": "context",
                "elements": context_elements
            })
        
        return blocks
    
    @staticmethod
    def create_attachments(
        message: str,
        severity: NotificationSeverity,
        template: SlackMessageTemplate,
        additional_fields: List[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        
        color = template.color_map.get(severity, "#cccccc")
        
        attachment = {
            "color": color,
            "text": message[:template.max_message_length],
            "ts": datetime.utcnow().timestamp() if template.include_timestamp else None,
            "fields": additional_fields or []
        }
        
        return [attachment]