/*!
 * Json Messaging消息服务客户端
 * 具有断连自动恢复功能，参见initWs()函数
 * @author shajunxing
 * @version 0.0.0.0
 */


(function ($) {
    /**
     * 获取消息客户端
     * 消息客户段具有下面一些事件：
     * onOpen() 客户端已连接
     * onError() WebSocket的onerror和消息服务器的错误帧都将触发该事件
     * onClose() 客户端已关闭事件
     * @return {*}
     */
    $.messageClient = function () {
        window.WebSocket = window.WebSocket || window.MozWebSocket;

        if (!window.WebSocket) {
            // 浏览器不支持WebSocket
            return null;
        }

        var client = {};

        // 局部消息回调函数，可针对每一个订阅单独定义回调函数
        client.messageListeners = {};
        // 打开、关闭和错误回调函数
        client.openListener = null;
        client.closeListener = null;
        client.errorListener = null;

        /**
         * 初始化client对象中的ws成员并和client绑定
         * 此函数将在连接错误或关闭后定时自动调用以自动重新连接
         */
        client.initWs = function () {
            if (location.protocol == 'https:') {
                client.ws = new WebSocket('wss://' + location.host + '/messaging');
            } else {
                client.ws = new WebSocket('ws://' + location.host + '/messaging');
            }

            client.ws.onmessage = function (message) {
                try {
                    var parsed = JSON.parse(message.data);
                    switch (parsed.type) {
                        case 'message':
                            // 消息帧
                            // 局部回调函数
                            for (var destination in client.messageListeners) {
                                if (client.messageListeners.hasOwnProperty(destination)) {
                                    if (client.messageListeners[destination]['pattern'].exec(parsed.match[0])) {
                                        if (client.messageListeners[destination]['listener']) {
                                            client.messageListeners[destination]['listener'](parsed.content, parsed.match);
                                        }
                                    }
                                }
                            }
                            break;
                        case 'error':
                            // 错误帧
                            console.warn('Server error: %s', parsed);
                            if (client.errorListener) {
                                client.errorListener();
                            }
                            break;
                        default:
                            // 未知帧
                            console.warn('Unknown message type %s', parsed.type);
                            break;
                    }
                } catch (e) {
                    console.warn(e);
                }
            };

            client.ws.onopen = function () {
                if (client.openListener) {
                    client.openListener();
                }
            };

            client.ws.onclose = function () {
                console.debug('websocket closed');
                if (client.closeListener) {
                    client.closeListener();
                }
                // 等待尝试重新连接
                // TODO: 是否会引起内存泄露？
                setTimeout(client.initWs, 3000);
            };

            client.ws.onerror = function () {
                console.debug('websocket error');
                if (client.errorListener) {
                    client.errorListener();
                }
                // 关闭连接
                client.ws.close();
            };
        };

        client.onOpen = function (listener) {
            client.openListener = listener;
        };

        client.onClose = function (listener) {
            client.closeListener = listener;
        };

        client.onError = function (listener) {
            client.errorListener = listener;
        };

        /**
         * 发布消息
         * @param content 内容
         * @param destination 目的地
         */
        client.publish = function (content, destination) {
            client.ws.send(JSON.stringify({
                type:'publish',
                destination:destination,
                content:content
            }));
        };

        /**
         * 订阅消息
         * @param destination 目的地（可以是正则表达式）
         * @param listener(content, match) 该订阅的回调函数
         */
        client.subscribe = function (destination, listener) {
            client.messageListeners[destination] = {};
            // 预编译
            client.messageListeners[destination]['pattern'] = new RegExp(destination);
            client.messageListeners[destination]['listener'] = listener;
            client.ws.send(JSON.stringify({
                type:'subscribe',
                destination:destination
            }));
        };

        /**
         * 取消订阅消息
         * @param destination 目的地
         */
        client.unsubscribe = function (destination) {
            delete client.messageListeners[destination];
            client.ws.send(JSON.stringify({
                type:'unsubscribe',
                destination:destination
            }));
        };

        /**
         * 关闭连接
         */
        client.close = function () {
            client.ws.close();
        };

        // 第一次初始化
        client.initWs();

        return client;
    };
}(jQuery));