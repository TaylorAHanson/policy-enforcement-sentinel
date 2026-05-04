import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self):
        self.server = settings.SMTP_SERVER
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL

    def send_warning(self, to_email: str, resource_id: str, message: str) -> bool:
        if not to_email or to_email == "unknown":
            logger.warning(f"Cannot send email to unknown owner for resource {resource_id}")
            return False
            
        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"Policy Violation Warning: {resource_id}"
            
            body = f"Hello,\n\nA policy violation was detected for your resource '{resource_id}'.\n\nDetails:\n{message}\n\nPlease review and remediate this issue.\n\n- Policy Enforcement Sentinel"
            msg.attach(MIMEText(body, 'plain'))
            
            # Use synchronous smtplib
            with smtplib.SMTP(self.server, self.port) as server:
                if self.username and self.password:
                    server.starttls()
                    server.login(self.username, self.password)
                server.send_message(msg)
                
            logger.info(f"Successfully sent warning email to {to_email} for resource {resource_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send warning email to {to_email}: {e}")
            return False

    def send_report(self, to_email: str, workspace: str, mode: str, violations: list) -> bool:
        if not to_email:
            return False
            
        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"Sentinel Run Report: {workspace} ({mode.upper()})"
            
            total_violations = len(violations)
            
            body = f"Hello,\n\nThe Policy Enforcement Sentinel has completed a run on workspace '{workspace}' in '{mode.upper()}' mode.\n\n"
            
            if mode.lower() == "audit":
                body += "*** AUDIT MODE ACTIVE: No destructive actions or warnings were actually executed. The actions listed below are what WOULD happen in enforcement mode. ***\n\n"
                
            body += f"Total Violations: {total_violations}\n\n"
            
            if total_violations > 0:
                body += "Violation Summary:\n"
                body += "-" * 50 + "\n"
                
                # Group by policy
                by_policy = {}
                for v in violations:
                    policy = v.get("policy", "Unknown")
                    if policy not in by_policy:
                        by_policy[policy] = []
                    by_policy[policy].append(v)
                    
                for policy, items in by_policy.items():
                    body += f"\nPolicy: {policy} ({len(items)} violations)\n"
                    for item in items[:5]: # Show max 5 per policy in email to avoid huge emails
                        body += f"  - [{item.get('action')}] {item.get('resource_type')}: {item.get('resource_id')}\n"
                    if len(items) > 5:
                        body += f"  ... and {len(items) - 5} more.\n"
                
                body += "\n" + "-" * 50 + "\n"
            
            body += "\nPlease check the Sentinel Dashboard for full details.\n\n- Policy Enforcement Sentinel"
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(self.server, self.port) as server:
                if self.username and self.password:
                    server.starttls()
                    server.login(self.username, self.password)
                server.send_message(msg)
                
            logger.info(f"Successfully sent run report to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send report email to {to_email}: {e}")
            return False
