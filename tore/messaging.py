#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Json Messaging服务器
"""
__author__ = 'shajunxing'
__version__ = ''

import json
import logging
import queue
import re
import socket
import threading
import tornado.ioloop
import tornado.netutil
import tornado.stack_context
import tornado.websocket
import uuid

class Exchange():
    """
    消息交换器
    封装Pub/Sub核心算法
    """

    def __init__(self):
        # 消息接收者字典，结构为：
        # {
        #     目的地正则表达式: {
        #         'compiled': 已编译的正则表达式;
        #         'callbacks': {
        #             uuid: 回调函数;
        #             ...
        #         }
        #     };
        #     ...
        # }
        self.__receivers = dict()
        self.__message_queue = queue.Queue()
        consumer_thread = threading.Thread(target=self.__push_consumer)
        consumer_thread.daemon = True
        consumer_thread.start()


    def add(self, destination_regex, callback):
        """
        增加一个正则表达式和回调函数
        所有匹配该正则表达式的消息将发送给回调函数
        返回标识该回调函数的ID（删除时候用）
        """
        id = str(uuid.uuid1())
        if destination_regex in self.__receivers:
            callbacks = self.__receivers[destination_regex]['callbacks']
            callbacks[id] = callback
        else:
            compiled = re.compile(destination_regex)
            self.__receivers[destination_regex] = {
                'compiled': compiled,
                'callbacks': {
                    id: callback
                }
            }
        return id

    def remove(self, id):
        # 如果某一个destinationRegex下面已经没有callback了，那么删除该destinationRegex条目
        # removeList为待删除的列表
        removeList = list()
        for destination_regex in self.__receivers:
            callbacks = self.__receivers[destination_regex]['callbacks']
            if id in callbacks:
                del callbacks[id]
            if not len(callbacks):
                removeList.append(destination_regex)
        for destination_regex in removeList:
            del self.__receivers[destination_regex]

    def push(self, message, destination):
        """
        发送一则消息，所有匹配目的地的回调函数将被调用
        """
        item = {
            'message': message,
            'destination': destination
        }
#        logging.debug('pushing: %s', item)
        self.__message_queue.put(item)

    def __push_consumer(self):
        """
        消息队列接收线程
        """
        while True:
            item = self.__message_queue.get()
#            logging.debug('consuming: %s', item)
            message = item['message']
            destination = item['destination']
            for destination_regex in self.__receivers:
                compiled_regex = self.__receivers[destination_regex]['compiled']
                m = compiled_regex.match(destination)
                if not m:
                    continue
                match_result = [destination]
                match_result += m.groups()
                callbacks = self.__receivers[destination_regex]['callbacks']
                for id in callbacks:
                    callbacks[id](message, match_result)
            self.__message_queue.task_done()

    def print_receivers(self):
        """
        打印所有接收者，测试用
        """
        for destination_regex in self.__receivers:
            print('"%s" {' % destination_regex)
            callbacks = self.__receivers[destination_regex]['callbacks']
            for id in callbacks:
                print('    "%s": %s' % (id, callbacks[id]))
            print('}')
        print()

# 全局唯一的交换器
exchange = Exchange()

def message_frame(content, match):
    """
    消息帧
    """
    return json.dumps({
        'type': 'message',
        'match': match,
        'content': content
    }, ensure_ascii=False)


def error_frame(content):
    """
    错误帧
    """
    return json.dumps({
        'type': 'error',
        'content': content
    }, ensure_ascii=False)


def publish_frame(content, destination):
    """
    发布帧
    """
    return json.dumps({
        'type': 'publish',
        'destination': destination,
        'content': content
    }, ensure_ascii=False)


def subscribe_frame(destination):
    """
    订阅帧
    """
    return json.dumps({
        'type': 'subscribe',
        'destination': destination
    }, ensure_ascii=False)


def unsubscribe_frame(destination):
    """
    取消订阅帧
    """
    return json.dumps({
        'type': 'unsubscribe',
        'destination': destination
    }, ensure_ascii=False)


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Json Messaging的WebSocket实现
    """

    def open(self):
        self.__address = self.request.connection.address
        logging.info('%s connected', self.__address)
        # 订阅列表
        self.__subscriptions = dict()

    def on_message(self, message):
        try:
            parsed = json.loads(message)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
                # 发布帧
                content = parsed['content']
                exchange.push(content, destination)
            elif type == 'subscribe':
                # 订阅帧
                if destination in self.__subscriptions:
                    raise Exception('Destination "%s" already exists' % destination)
                else:
                    id = exchange.add(destination, self.callback)
                    self.__subscriptions[destination] = id
                    logging.info('%s subscribes "%s"', self.__address, destination)
            elif type == 'unsubscribe':
                # 取消订阅帧
                if destination not in self.__subscriptions:
                    raise Exception('Destination "%s" not exists' % destination)
                else:
                    id = self.__subscriptions[destination]
                    exchange.remove(id)
                    del self.__subscriptions[destination]
            else:
                raise Exception('Unknown message type "%s"', type)
        except Exception as ex:
            logging.warning(ex)
            # 所有异常统一发回客户端
            self.write_message(error_frame(str(ex)))

    def on_close(self):
        logging.info('%s disconnected, all subscription from which will be cleaned', self.__address)
        for destination in self.__subscriptions:
            id = self.__subscriptions[destination]
            exchange.remove(id)
        del self.__subscriptions

    def callback(self, content, match):
        """
        消息回调函数
        """
        self.write_message(message_frame(content, match))


class TCPConnection():
    """
    Json Messaging的TCP单条连接处理
    """

    def __init__(self, stream, address):
        self.__stream = stream
        self.__address = address
        logging.info('%s connected', self.__address)
        # 订阅列表
        self.__subscriptions = dict()
        self.__stream.set_close_callback(self.__on_close)
        self.__message_callback = tornado.stack_context.wrap(self.__on_message)
        self.__stream.read_until(b'\0', self.__message_callback)

    def __on_message(self, message):
        """
        处理客户端发来的消息帧
        """
        try:
            # 注意要去掉末尾的'\0'
            msg = message[:-1].decode()
            logging.debug(msg)
            parsed = json.loads(msg)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
                # 发布帧
                content = parsed['content']
                exchange.push(content, destination)
            elif type == 'subscribe':
                # 订阅帧
                if destination in self.__subscriptions:
                    raise Exception('Destination "%s" already exists' % destination)
                else:
                    id = exchange.add(destination, self.__callback)
                    self.__subscriptions[destination] = id
                    logging.info('%s subscribes "%s"', self.__address, destination)
            elif type == 'unsubscribe':
                # 取消订阅帧
                if destination not in self.__subscriptions:
                    raise Exception('Destination "%s" not exists' % destination)
                else:
                    id = self.__subscriptions[destination]
                    exchange.remove(id)
                    del self.__subscriptions[destination]
            else:
                raise Exception('Unknown message type "%s"', type)
        except Exception as ex:
            logging.warning(ex)
            # 所有异常统一发回客户端
            if not self.__stream.closed():
                self.__stream.write(error_frame(str(ex)).encode() + b'\0')

        if not self.__stream.closed():
            self.__stream.read_until(b'\0', self.__message_callback)

    def __on_close(self):
        """
        处理Socket关闭事件
        """
        logging.info('%s disconnected, all subscription from which will be cleaned', self.__address)
        for destination in self.__subscriptions:
            id = self.__subscriptions[destination]
            exchange.remove(id)
        del self.__subscriptions

    def __callback(self, content, match):
        """
        消息回调函数
        """
        if not self.__stream.closed():
            self.__stream.write(message_frame(content, match).encode() + b'\0')


class TCPServer(tornado.netutil.TCPServer):
    """
    Json Messaging的TCP服务器
    """

    def handle_stream(self, stream, address):
        TCPConnection(stream, address)


class UDPServer():
    """
    Json Messaging的UDP服务器
    """

    def __init__(self):
        self.__sock = socket.socket(type=socket.SOCK_DGRAM)

    def listen(self, port):
        self.__sock.bind(('', port))
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__sock.setblocking(0)
        io_loop = tornado.ioloop.IOLoop.instance()
        io_loop.add_handler(self.__sock.fileno(), self.__handler, io_loop.READ)

    def __handler(self, fd, events):
        data, addr = self.__sock.recvfrom(1024)
        try:
            msg = data.decode()
            logging.debug(msg)
            parsed = json.loads(msg)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
                # UDP只处理发布帧
                content = parsed['content']
                exchange.push(content, destination)
        except Exception as ex:
            logging.warning(ex)


class UDPClient():
    """
    UDP客户端，只支持消息发布
    """

    def __init__(self, host='localhost', port=8154):
        """
        host: 消息服务器地址
        port: 消息服务器端口
        """
        # 客户端套接字
        self.__socket = socket.socket(type=socket.SOCK_DGRAM)
        self.__socket.connect((host, port))

    def publish(self, content, destination):
        """
        发布一则消息
        content: 消息内容，类型Python对象
        destination: 消息目的地字符串
        """
        try:
            self.__socket.send(publish_frame(content, destination).encode())
        except Exception as ex:
            logging.warning(ex)

    def close(self):
        """
        关闭所有资源
        """
        try:
            self.__socket.shutdown(socket.SHUT_RDWR)
            self.__socket.close()
        except Exception as ex:
            logging.warning(ex)