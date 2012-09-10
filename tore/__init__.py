#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Tornado增强
包含了实用的帮助类和函数
"""
import logging
import os
import tornado.httpserver
import tornado.ioloop
import tore.messaging
import tore.web

__author__ = 'shajunxing'
__version__ = ''

def start_server(**settings):
    """
    一步到位启动一站式的服务器
    """
    port = settings.get('port') or 80
    application = tore.web.Application(**settings)
    if settings.get('encryption'):
        # 网站根目录，默认为当前目录
        root_dir = settings.get('root_dir')
        if not root_dir:
            root_dir = os.getcwd()
        server = tornado.httpserver.HTTPServer(application, ssl_options={
            'certfile': os.path.join(root_dir, settings.get('certfile')),
            'keyfile': os.path.join(root_dir, settings.get('keyfile')),
            })
        server.listen(port)
    else:
        application.listen(port)
    logging.info('HTTP server started at 0.0.0.0:%d', port)

    messaging_tcp_port = settings.get('messaging_tcp_port')
    if messaging_tcp_port:
        tcp_server = tore.messaging.TCPServer()
        tcp_server.listen(messaging_tcp_port)
        logging.info('Json Messaging TCP server started at 0.0.0.0:%d', messaging_tcp_port)

    messaging_udp_port = settings.get('messaging_udp_port')
    if messaging_udp_port:
        udp_server = tore.messaging.UDPServer()
        udp_server.listen(messaging_udp_port)
        logging.info('Json Messaging UDP server started at 0.0.0.0:%d', messaging_udp_port)

    tornado.ioloop.IOLoop.instance().start()