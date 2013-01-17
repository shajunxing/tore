# -*- coding: UTF-8 -*-

import os
import sys

def get_exec_dir():
    """
    get the absolute dir of callee
    Notice: must be invoked from __main__ to get the correct result
    """
    if hasattr(sys, 'frozen'):
        # packed by cx_Freeze
        # return absolute dir of packed executable
        return os.path.dirname(sys.executable)
    else:
        # return where callee source is located
        frame = sys._getframe(0)
        this_filename = frame.f_code.co_filename
        while frame.f_code.co_filename == this_filename:
            frame = frame.f_back
        return os.path.dirname(frame.f_code.co_filename)
