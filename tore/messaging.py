# -*- coding: UTF-8 -*-

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

class _Exchange():
    """
    The message exchanger, contains core algorithm of pub/sub messaging model
    """

    def __init__(self):
        # receivers dictionary, which structure is:
        #
        # {
        #     <destination regex>: {
        #         'compiled': <compiled regular expression>,
        #         'callbacks': {
        #             uuid: <callback function>,
        #             ...
        #         }
        #     };
        #     ...
        # }
        self.__receivers = dict()
        self.__receivers_lock = threading.Lock()
        self.__message_queue = queue.Queue()
        consumer_thread = threading.Thread(target=self.__push_consumer)
        consumer_thread.daemon = True
        consumer_thread.start()


    def add(self, destination_regex, callback):
        """
        add a destination regex and corresponding callback
        all the messages matched destination will trigger the callback
        return an identification for callback removal
        """
        id = str(uuid.uuid1())
        self.__receivers_lock.acquire()
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
        self.__receivers_lock.release()
        return id

    def remove(self, id):
        """
        remove a callback by it's identification
        """
        # if no callbacks in one destination regex, it will be removed to save memory
        # removeList is a list for removal
        removeList = list()
        self.__receivers_lock.acquire()
        for destination_regex in self.__receivers:
            callbacks = self.__receivers[destination_regex]['callbacks']
            if id in callbacks:
                del callbacks[id]
            if not len(callbacks):
                removeList.append(destination_regex)
        for destination_regex in removeList:
            del self.__receivers[destination_regex]
        self.__receivers_lock.release()

    def push(self, message, destination):
        """
        push a message to queue
        """
        item = {
            'message': message,
            'destination': destination
        }
        #        logging.debug('pushing: %s', item)
        self.__message_queue.put(item)

    def __push_consumer(self):
        """
        message queue consumer thread
        all the destination matched callbacks will be triggered
        """
        while True:
            item = self.__message_queue.get()
            #            logging.debug('consuming: %s', item)
            message = item['message']
            destination = item['destination']
            self.__receivers_lock.acquire()
            for destination_regex in self.__receivers:
                compiled_regex = self.__receivers[destination_regex]['compiled']
                m = compiled_regex.match(destination)
                if not m:
                    continue
                match_result = [destination]
                match_result += m.groups()
                callbacks = self.__receivers[destination_regex]['callbacks']
                for id in callbacks:
                    # May raise exception "AttributeError: 'NoneType' object has no attribute 'write_message'" sometimes after WebSocket closed
                    try:
                        callbacks[id](message, match_result)
                    except Exception as ex:
                        logging.warning(ex)
            self.__receivers_lock.release()
            self.__message_queue.task_done()

    def print_receivers(self):
        """
        print all receivers, for test purpose
        """
        self.__receivers_lock.acquire()
        for destination_regex in self.__receivers:
            print('"%s" {' % destination_regex)
            callbacks = self.__receivers[destination_regex]['callbacks']
            for id in callbacks:
                print('    "%s": %s' % (id, callbacks[id]))
            print('}')
        self.__receivers_lock.release()
        print()

# global message exchange
exchange = _Exchange()

def message_frame(content, match):
    """
    message frame
    """
    return json.dumps({
        'type': 'message',
        'match': match,
        'content': content
    }, ensure_ascii=False)


def error_frame(content):
    """
    error frame
    """
    return json.dumps({
        'type': 'error',
        'content': content
    }, ensure_ascii=False)


def publish_frame(content, destination):
    """
    message publish frame
    """
    return json.dumps({
        'type': 'publish',
        'destination': destination,
        'content': content
    }, ensure_ascii=False)


def subscribe_frame(destination):
    """
    message subscribe frame
    """
    return json.dumps({
        'type': 'subscribe',
        'destination': destination
    }, ensure_ascii=False)


def unsubscribe_frame(destination):
    """
    message unsubscribe frame
    """
    return json.dumps({
        'type': 'unsubscribe',
        'destination': destination
    }, ensure_ascii=False)


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    """
    WebSocket implementation
    """

    def open(self):
        self.__address = self.request.connection.address
        logging.debug('%s connected', self.__address)
        self.__subscriptions = dict()

    def on_message(self, message):
        logging.debug(self.request.headers.get('Authorization'))
        try:
            parsed = json.loads(message)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
            #                content = parsed['content']
            #                exchange.push(content, destination)
                # 此处为了安全起见，禁用发布功能，如果需要发布消息，可以走REST接口
                raise Exception('Publish is not allowed on WebSocket')
            elif type == 'subscribe':
                if destination in self.__subscriptions:
                    raise Exception('Destination "%s" already exists' % destination)
                else:
                    id = exchange.add(destination, self.callback)
                    self.__subscriptions[destination] = id
                    logging.debug('%s subscribes "%s"', self.__address, destination)
            elif type == 'unsubscribe':
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
            self.write_message(error_frame(str(ex)))

    def on_close(self):
        logging.debug('%s disconnected, all subscription from which will be cleaned', self.__address)
        for destination in self.__subscriptions:
            id = self.__subscriptions[destination]
            exchange.remove(id)
        del self.__subscriptions

    def callback(self, content, match):
        """
        message callback
        """
        self.write_message(message_frame(content, match))


class TCPConnection():
    """
    TCP connection handler
    """

    def __init__(self, stream, address):
        self.__stream = stream
        self.__address = address
        logging.debug('%s connected', self.__address)
        self.__subscriptions = dict()
        self.__stream.set_close_callback(self.__on_close)
        self.__message_callback = tornado.stack_context.wrap(self.__on_message)
        self.__stream.read_until(b'\0', self.__message_callback)

    def __on_message(self, message):
        """
        handle client frames
        """
        try:
            # Notice to remove tailed '\0'
            msg = message[:-1].decode()
            logging.debug(msg)
            parsed = json.loads(msg)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
                content = parsed['content']
                exchange.push(content, destination)
            elif type == 'subscribe':
                if destination in self.__subscriptions:
                    raise Exception('Destination "%s" already exists' % destination)
                else:
                    id = exchange.add(destination, self.__callback)
                    self.__subscriptions[destination] = id
                    logging.debug('%s subscribes "%s"', self.__address, destination)
            elif type == 'unsubscribe':
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
            if not self.__stream.closed():
                self.__stream.write(error_frame(str(ex)).encode() + b'\0')

        if not self.__stream.closed():
            self.__stream.read_until(b'\0', self.__message_callback)

    def __on_close(self):
        """
        handle socket close event
        """
        logging.debug('%s disconnected, all subscription from which will be cleaned', self.__address)
        for destination in self.__subscriptions:
            id = self.__subscriptions[destination]
            exchange.remove(id)
        del self.__subscriptions

    def __callback(self, content, match):
        """
        message callback
        """
        if not self.__stream.closed():
            self.__stream.write(message_frame(content, match).encode() + b'\0')


class TCPServer(tornado.netutil.TCPServer):
    """
    TCP implementation
    """

    def handle_stream(self, stream, address):
        TCPConnection(stream, address)


class UDPServer():
    """
    UDP implementation
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
#            logging.debug(msg)
            parsed = json.loads(msg)
            type = parsed['type']
            destination = parsed['destination']
            if type == 'publish':
                content = parsed['content']
                exchange.push(content, destination)
        except Exception as ex:
            logging.warning(ex)


class UDPClient():
    """
    UDP client, only message publishing is supported
    """

    def __init__(self, host='localhost', port=8154):
        """
        host: message server address
        port: message server port
        """
        # client socket
        self.__socket = socket.socket(type=socket.SOCK_DGRAM)
        self.__socket.connect((host, port))

    def publish(self, content, destination):
        try:
            self.__socket.send(publish_frame(content, destination).encode())
        except Exception as ex:
            logging.warning(ex)

    def close(self):
        """
        close all resources
        """
        try:
            self.__socket.shutdown(socket.SHUT_RDWR)
            self.__socket.close()
        except Exception as ex:
            logging.warning(ex)