"""Callable tools available to the chat agent."""

from fae.tools.bash import BASH_TOOLS, dispatch_bash_tool
from fae.tools.filesystem import FILESYSTEM_TOOLS, dispatch_filesystem_tool
from fae.tools.git import GIT_TOOLS, dispatch_git_tool
from fae.tools.weather import WEATHER_TOOLS, dispatch_weather_tool

__all__ = [
    "BASH_TOOLS",
    "FILESYSTEM_TOOLS",
    "GIT_TOOLS",
    "WEATHER_TOOLS",
    "dispatch_bash_tool",
    "dispatch_filesystem_tool",
    "dispatch_git_tool",
    "dispatch_weather_tool",
]
