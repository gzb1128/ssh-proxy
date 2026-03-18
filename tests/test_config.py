#!/usr/bin/env python3
"""Unit tests for ConfigLoader"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ssh_proxy.config import ConfigLoader


class TestConfigLoaderInit(unittest.TestCase):
    """Test ConfigLoader initialization"""

    def test_init_with_valid_path(self):
        """Test initialization with a valid path"""
        loader = ConfigLoader('some/path/config.yaml')
        self.assertEqual(loader.config_path, 'some/path/config.yaml')
        self.assertIsNone(loader.config)

    def test_init_path_expansion(self):
        """Test that path is stored as-is (expansion happens during load)"""
        loader = ConfigLoader('~/config.yaml')
        self.assertEqual(loader.config_path, '~/config.yaml')


class TestConfigLoad(unittest.TestCase):
    """Test config file loading"""

    def setUp(self):
        """Set up test fixtures directory path"""
        self.fixtures_dir = Path(__file__).parent / 'fixtures'

    def test_load_valid_config(self):
        """Test loading a valid configuration file"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        self.assertIsNotNone(config)
        self.assertIn('remote_server', config)
        self.assertIn('services', config)
        self.assertEqual(config['remote_server']['host'], '192.168.1.100')
        self.assertEqual(config['remote_server']['ssh_name'], 'my-server')
        self.assertIn('web-app', config['services'])
        self.assertIn('api-server', config['services'])

    def test_load_nonexistent_file(self):
        """Test loading a non-existent file should exit with error"""
        loader = ConfigLoader('/nonexistent/path/config.yaml')
        with self.assertRaises(FileNotFoundError):
            # The file check happens before sys.exit is called
            # We expect FileNotFoundError when trying to open the file
            with patch('sys.exit') as mock_exit:
                loader.load()

    def test_load_config_with_template(self):
        """Test loading config with Jinja2 templates"""
        config_path = self.fixtures_dir / 'config_with_template.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        # Template should be rendered
        self.assertEqual(config['remote_server']['host'], '10.0.0.50')
        self.assertEqual(config['services']['service1']['remote_port'], '9000')
        self.assertEqual(config['services']['service2']['host'], '10.0.0.50')


class TestConfigValidation(unittest.TestCase):
    """Test config validation"""

    def setUp(self):
        """Set up test fixtures directory path"""
        self.fixtures_dir = Path(__file__).parent / 'fixtures'

    def test_validate_complete_config(self):
        """Test validation of a complete config"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        # Should not raise any exception
        config = loader.load()
        self.assertIsNotNone(config)

    def test_validate_missing_remote_server(self):
        """Test validation fails when remote_server is missing"""
        config_path = self.fixtures_dir / 'invalid_config_missing_remote.yaml'
        loader = ConfigLoader(str(config_path))
        with patch('sys.exit') as mock_exit:
            try:
                loader.load()
            except KeyError:
                # KeyError may be raised if sys.exit is mocked but code continues
                pass
            # sys.exit should be called at least once for the missing remote_server
            self.assertTrue(mock_exit.called)
            # Check that it was called with exit code 1
            self.assertEqual(mock_exit.call_args[0][0], 1)

    @patch('sys.exit')
    def test_validate_missing_services(self, mock_exit):
        """Test validation fails when services is missing"""
        config_path = self.fixtures_dir / 'invalid_config_missing_services.yaml'
        loader = ConfigLoader(str(config_path))
        loader.load()
        mock_exit.assert_called_once_with(1)

    @patch('sys.exit')
    def test_validate_missing_host_or_ssh_name(self, mock_exit):
        """Test validation fails when remote_server is missing required fields"""
        config_path = self.fixtures_dir / 'invalid_config_missing_fields.yaml'
        loader = ConfigLoader(str(config_path))
        loader.load()
        mock_exit.assert_called_once_with(1)


class TestTemplateRendering(unittest.TestCase):
    """Test Jinja2 template rendering"""

    def setUp(self):
        """Set up test fixtures directory path"""
        self.fixtures_dir = Path(__file__).parent / 'fixtures'

    def test_render_simple_template(self):
        """Test simple template rendering with env variables"""
        config_path = self.fixtures_dir / 'config_with_template.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        # Template {{ env.SERVER_IP }} should be rendered to 10.0.0.50
        self.assertEqual(config['remote_server']['host'], '10.0.0.50')

    def test_render_complex_template(self):
        """Test multiple template variables in config"""
        config_path = self.fixtures_dir / 'config_with_template.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        # Both SERVER_IP and SERVER_PORT should be rendered
        self.assertEqual(config['remote_server']['host'], '10.0.0.50')
        self.assertEqual(config['services']['service1']['remote_port'], '9000')

    def test_render_nested_template(self):
        """Test template rendering in nested structures"""
        config_path = self.fixtures_dir / 'config_with_template.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        # Template in nested service config
        self.assertEqual(config['services']['service2']['host'], '10.0.0.50')

    def test_render_no_template(self):
        """Test that strings without template markers pass through unchanged"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        config = loader.load()

        # Plain strings should remain unchanged
        self.assertEqual(config['remote_server']['host'], '192.168.1.100')
        self.assertIsInstance(config['services']['web-app']['remote_port'], int)


class TestGetServices(unittest.TestCase):
    """Test service list retrieval"""

    def setUp(self):
        """Set up test fixtures directory path"""
        self.fixtures_dir = Path(__file__).parent / 'fixtures'

    def test_get_all_services(self):
        """Test getting all services without exclusion"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        loader.load()
        services = loader.get_services()

        self.assertEqual(services, {'web-app', 'api-server'})

    def test_get_services_with_exclude(self):
        """Test getting services with some excluded"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        loader.load()
        services = loader.get_services(exclude_services={'web-app'})

        self.assertEqual(services, {'api-server'})

    def test_get_services_empty_exclude(self):
        """Test getting services with empty exclusion set"""
        config_path = self.fixtures_dir / 'valid_config.yaml'
        loader = ConfigLoader(str(config_path))
        loader.load()
        services = loader.get_services(exclude_services=set())

        self.assertEqual(services, {'web-app', 'api-server'})


if __name__ == '__main__':
    unittest.main()
