#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Example Server
"""
__author__ = 'shajunxing'
__version__ = ''

import platform
import threading
import time
import tore
import tore.messaging
import tore.web

def authenticate(username, password):
    """
    Sample authentication method, do nothing so you can login using any username and password
    """
    return True


def authorize(username, path):
    """
    Sample authorization method, also do nothing
    """
    return True


class SystemInformationHandler(tore.web.JsonHandler):
    """
    Ajax handler of getting some system information
    """
    @tore.web.authenticated
    def get(self, *args, **kwargs):
        self.write_object({
            'username': self.current_user,
            'platform': platform.platform(),
            'processor': platform.processor()
        })

def timer():
    """
    Sample message publisher
    """
    while True:
        time.sleep(1)
        tore.messaging.exchange.push(time.strftime('%Y-%m-%d %H:%M:%S'), '/time')

if __name__ == '__main__':
    timer_thread = threading.Thread(target=timer)
    timer_thread.daemon = True
    timer_thread.start()
    tore.start_server(**{
        'port': 8080,
        'gzip': True,
        'debug': True,
        'authentication': authenticate,
        'authorization': authorize,
        'handlers': [
            ('^/system$', SystemInformationHandler),
        ]
    })