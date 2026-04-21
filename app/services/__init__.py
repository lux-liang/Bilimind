"""
BiliMind 知识树导航系统

服务模块初始化
"""

# Keep package initialization lightweight. Individual services import optional
# third-party tools such as qrcode, dashscope, ffmpeg, or vector stores; importing
# them here would break offline demo scripts that only need one service module.

__all__ = []
