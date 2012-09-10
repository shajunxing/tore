#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""

"""
__author__ = 'shajunxing'
__version__ = ''

import os
import sys

def get_exec_dir():
    """
    获取调用脚本所在的目录
    注意：必须从程序的主文件中直接调用该函数才能获得程序运行的目录
    """
    if hasattr(sys, 'frozen'):
        # 使用cx_Freeze等工具打包了
        # 返回打包后的可执行程序目录
        return os.path.dirname(sys.executable)
    else:
        # 返回调用方的Python源文件所在目录
        frame = sys._getframe(0)
        this_filename = frame.f_code.co_filename
        while frame.f_code.co_filename == this_filename:
            frame = frame.f_back
        return os.path.dirname(frame.f_code.co_filename)
