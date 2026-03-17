# Contributing Guide

Thank you for your interest in contributing to SSH Proxy Manager. This document outlines the guidelines and procedures for contributing to the project.

## Table of Contents

- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Pull Requests](#pull-requests)
- [Development Setup](#development-setup)
- [Coding Guidelines](#coding-guidelines)
- [Testing](#testing)
- [Documentation](#documentation)

## How to Contribute

### Reporting Bugs

Before submitting a bug report, please check existing issues to avoid duplicates. When creating a bug report, provide the following information:

- A clear and descriptive title
- Steps to reproduce the issue
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, dependency versions)
- Relevant log output or error messages
- Any configuration that helps reproduce the issue

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When submitting an enhancement request, include:

- A clear and descriptive title
- A detailed description of the proposed enhancement
- Rationale for why this enhancement would be beneficial
- Examples of how the enhancement would be used
- Any potential implementation considerations

### Pull Requests

1. Fork the repository and create a feature branch from `main`
2. Make your changes following the coding guidelines
3. Test your changes thoroughly
4. Update documentation as needed
5. Submit a pull request with a clear description of the changes

Pull request titles should follow this format:

```
<type>: <description>
```

Types include:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

## Development Setup

### Prerequisites

- Python 3.6 or higher
- Git

### Setup Steps

```bash
# Clone your fork
git clone https://github.com/<your-username>/ssh-proxy.git
cd ssh-proxy

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy example config for testing
cp config.yaml.example config.yaml
```

## Coding Guidelines

### Python Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Add docstrings to public functions and classes
- Keep functions focused and reasonably sized (under 50 lines when possible)
- Use type hints where appropriate

### Code Organization

- Maintain single-file structure for simplicity (ssh_proxy.py)
- Use classes to organize related functionality
- Separate concerns: configuration loading, SSH management, HTTP handling
- Prefer composition over inheritance

### Error Handling

- Use specific exception types
- Provide informative error messages
- Handle expected errors gracefully
- Log errors with context for debugging

### Commit Messages

Write clear and descriptive commit messages following this format:

```
<type>: <subject>

<body>

<footer>
```

Example:

```
feat: add support for custom SSH options

Add ssh_options field to config that allows users to specify
additional SSH command options like -o ConnectTimeout=10.

Fixes #123
```

## Testing

Before submitting a pull request, test your changes:

1. **Manual Testing**
   - Test with different configurations
   - Verify startup and shutdown behavior
   - Test with missing or invalid configuration

2. **Edge Cases**
   - Empty services list
   - Invalid port numbers
   - Missing configuration fields
   - Network failures

3. **Signal Handling**
   - Ctrl+C graceful shutdown
   - Multiple interrupt handling

4. **Backward Compatibility**
   - Ensure existing configurations continue to work
   - Test with older Python versions (3.6+)

## Documentation

When making changes that affect user-facing behavior:

- Update `README.md` for new features or changed behavior
- Update `config.yaml.example` for new configuration options
- Add inline comments for complex logic
- Update docstrings for modified functions

## Getting Help

If you have questions about contributing, open an issue with the "question" label or reach out to the maintainers.

Thank you for your contribution.
