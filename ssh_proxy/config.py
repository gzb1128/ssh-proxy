"""Configuration loading and template rendering"""

from pathlib import Path
import sys

import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined

# Template markers for detecting if rendering is needed
TEMPLATE_MARKERS = ('{{', '}}')


class ConfigLoader:
    """Configuration loader with Jinja2 template support"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = None
        self._jinja_env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    def _render_template(self, value: str, env_vars: dict):
        """Render Jinja2 template string"""
        if not isinstance(value, str):
            return value

        # Quick check: if string doesn't contain template markers, return as-is
        if TEMPLATE_MARKERS[0] not in value or TEMPLATE_MARKERS[1] not in value:
            return value

        try:
            template = self._jinja_env.from_string(value)
            return template.render(env=env_vars)
        except Exception as e:
            print(f"Warning: Template rendering failed for '{value}': {e}")
            return value

    def _render_value(self, value, env_vars: dict):
        """Recursively render a single value"""
        if isinstance(value, dict):
            # Skip 'env' key, it doesn't need rendering
            return {k: self._render_value(v, env_vars) for k, v in value.items() if k != 'env'}
        elif isinstance(value, list):
            return [self._render_value(item, env_vars) for item in value]
        elif isinstance(value, str):
            return self._render_template(value, env_vars)
        else:
            return value

    def _render_config_templates(self, config: dict) -> dict:
        """Recursively render all templates in config"""
        env_vars = config.get('env', {})
        return self._render_value(config, env_vars)

    def load(self) -> dict:
        """Load and validate configuration file"""
        config_path = Path(self.config_path).expanduser()
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}")
            sys.exit(1)

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # Render templates in config
        self.config = self._render_config_templates(self.config)

        # Validate config
        self._validate_config()

        return self.config

    def _validate_config(self):
        """Validate required configuration fields"""
        if 'remote_server' not in self.config:
            print("Error: Config missing 'remote_server' section")
            sys.exit(1)

        if 'services' not in self.config:
            print("Error: Config missing 'services' section")
            sys.exit(1)

        # Validate remote_server fields
        remote_server = self.config['remote_server']
        if 'host' not in remote_server or 'ssh_name' not in remote_server:
            print("Error: remote_server config missing 'host' or 'ssh_name'")
            sys.exit(1)

    def get_services(self, exclude_services: set = None) -> set:
        """Get list of services to proxy (excluding specified ones)"""
        if exclude_services is None:
            exclude_services = set()
        all_services = set(self.config['services'].keys())
        return all_services - exclude_services
