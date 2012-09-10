#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""

"""
__author__ = 'shajunxing'
__version__ = ''

import base64
import functools
import io
import json
import logging
import os
import tornado.httpserver
import tornado.ioloop
import tornado.template
import tornado.web
import tore.messaging

class RequestHandler(tornado.web.RequestHandler):
    """
    Tornado默认请求处理器的增强版
    能自动加载并执行位于和模板相同目录下的“模板名.py”文件，自动将所有名字引入模板中
    """

    def create_template_loader(self, template_path):
        """
        替换Tornado默认的Loader
        """
        settings = self.application.settings
        if "template_loader" in settings:
            return settings["template_loader"]
        kwargs = {}
        if "autoescape" in settings:
            # autoescape=None means "no escaping", so we have to be sure
            # to only pass this kwarg if the user asked for it.
            kwargs["autoescape"] = settings["autoescape"]

        # 此处替换
        return Loader(template_path, **kwargs)


class Loader(tornado.template.Loader):
    """
    配合RequestHandler使用
    """

    def _create_template(self, name):
        """
        替换Tornado默认的Template
        """
        path = os.path.join(self.root, name)
        f = open(path, "rb")
        template_string = f.read()
        f.close()
        try:
            f = open(path + '.py', "rb")
            source_string = f.read()
            f.close()
        except Exception:
            source_string = b''
        template = Template(template_string, source_string, name=name, loader=self)
        return template


class Template(tornado.template.Template):
    """
    配合Loader使用
    在默认Template基础上加入自动加载“模板名.py”文件的功能
    """

    def __init__(self, template_string, source_string, name="<string>", loader=None,
                 compress_whitespace=None, autoescape=tornado.template._UNSET):
        """
        增加source_string参数，意为模板对应的源文件的内容
        """
        self.source_string = source_string.decode('utf-8')
        tornado.template.Template.__init__(self, template_string, name, loader, compress_whitespace, autoescape)

    def _generate_python(self, loader, compress_whitespace):
        buffer = io.StringIO()
        try:
            # named_blocks maps from names to _NamedBlock objects
            named_blocks = {}
            ancestors = self._get_ancestors(loader)
            ancestors.reverse()
            for ancestor in ancestors:
                ancestor.find_named_blocks(loader, named_blocks)
            self.file.find_named_blocks(loader, named_blocks)
            writer = tornado.template._CodeWriter(buffer, named_blocks, loader, ancestors[0].template,
                compress_whitespace)
            ancestors[0].generate(writer)

            # 附加源代码，从祖先一直加到自己
            for ancestor in ancestors:
                buffer.write('\n\n')
                buffer.write(ancestor.template.source_string)

            return buffer.getvalue()
        finally:
            buffer.close()

    def generate(self, **kwargs):
        # 调试输出编译后的代码
        formatted_code = tornado.template._format_code(self.code).rstrip()
        logging.debug("%s code:\n%s", self.name, formatted_code)
        return tornado.template.Template.generate(self, **kwargs)


def authenticated(method):
    """
    HTTP基本身份认证修饰符，修改自tornado.web的同名方法
    修饰get、post等方法
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        authentication_method = self.settings.get('authentication')
        if authentication_method:
            try:
                auth_header = self.request.headers['Authorization']
                decoded = base64.b64decode(auth_header[6:].encode()).decode().split(':')
                username = decoded[0]
                password = decoded[1]
                if authentication_method(username, password):
                    self._current_user = username
                else:
                    self._current_user = None
            except Exception as ex:
                logging.warning(ex)
                self._current_user = None

            if not self._current_user:
                self.set_header('WWW-Authenticate', 'Basic')
                self.set_status(401)
                self.set_header('Content-Type', 'text/html; charset=UTF-8')
                self.write(_unauthenticated_html)
                return

        return method(self, *args, **kwargs)

    return wrapper


def authorized(method):
    """
    授权修饰符，用于判断某用户是否有权限访问某Web页面
    配合AuthHandler使用，修饰get、post等方法
    用到全局配置中的“authorization”属性，该属性指向一个函数，参数为用户名和不带参数和锚点的页面url
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        authorization_method = self.settings.get('authorization')
        if authorization_method and not authorization_method(self.current_user, self.request.path):
            self.set_status(403)
            self.set_header('Content-Type', 'text/html; charset=UTF-8')
            self.write(_unauthorized_html)
            return

        return method(self, *args, **kwargs)

    return wrapper


class TemplateHandler(RequestHandler):
    """
    高级模板处理器
    能自动加载并执行位于和模板相同目录下的“模板名.py”文件，自动将所有名字引入模板中
    支持全局的"debug"和"template_path"设置
    支持所有Tornado的模板语法，但是要注意的是：受限于Tornado的模板机制，如果模板有继承、扩展等机制，
    只处理子模板对应的.py文件，所以父模板中包含的变量要在子模板对应的.py文件中声明
    """

    @authenticated
    @authorized
    def get(self, *args, **kwargs):
        path = args[0]
        self.render(path)

    @authenticated
    @authorized
    def post(self, *args, **kwargs):
        """
        转GET处理
        """
        self.get(*args, **kwargs)


class JsonHandler(RequestHandler):
    """
    Json处理器，一般用于RESTful WebService
    RequestHandler的write只支持把字典类型的值输出为Json格式，建议不用
    """

    def __set_json_header(self):
        """
        设置Json HTTP头
        """
        self.set_header('Content-Type', 'application/json; charset=UTF-8')

    def write_object(self, obj):
        """
        把Python对象输出为Json格式
        """
        self.__set_json_header()
        if self.application.settings.get('debug'):
            self.write(json.dumps(obj, indent=4, ensure_ascii=False))
        else:
            self.write(json.dumps(obj))

    def write_text(self, txt):
        """
        直接输出Json格式的文本
        不对文本做编码和语法检查
        """
        self.__set_json_header()
        self.write(txt)

    def get_params_as_dict(self):
        """
        获取字典包装的查询字幅串请求参数列表
        """
        ret = {}
        for k in list(self.request.arguments.keys()):
            ret[k] = self.get_argument(k)
        return ret

    def get_body_as_text(self):
        """
        获取HTTP请求报文体
        """
        return self.request.body.decode()

    def get_body_as_object(self):
        """
        获取Json格式的HTTP请求报文体
        转换为Python对象
        """
        return json.loads(self.get_body_as_text())


class ForbiddenFileHandler(RequestHandler):
    """
    对于禁止访问的文件，欺骗性地返回404
    """

    def get(self, *args, **kwargs):
        """
        GET返回404，其它操作默认都返回405
        """
        raise tornado.web.HTTPError(404)


class Application(tornado.web.Application):
    """
    增强版的Application类，为一站式服务提供支持
    结合全局设置中的“root_dir”自动设置模板和静态目录
    """

    def __init__(self, handlers, **settings):
        # 网站根目录，默认为当前目录
        root_dir = settings.get('root_dir')
        if not root_dir:
            root_dir = os.getcwd()
            # 模板和静态文件的根目录，为网站根目录下的“web”目录
        web_root_dir = os.path.join(root_dir, 'web')
        default_settings = {
            # 模板的物理路径，供TemplateHandler使用
            'template_path': web_root_dir
        }
        default_settings.update(settings)
        default_handlers = [
            # 默认页
            ('/', tornado.web.RedirectHandler, dict(url='/web/index.t')),
            ('/web/(.*?\.t)', TemplateHandler),
            ('/web/.*?\.py', ForbiddenFileHandler),
            ('/web/(.*)', tornado.web.StaticFileHandler, dict(path=web_root_dir)),
            # 消息服务的WebSocket接口
            ('/messaging', tore.messaging.WebSocketHandler)
        ]
        if handlers:
            default_handlers += handlers
        tornado.web.Application.__init__(self, default_handlers, **default_settings)

    def log_request(self, handler):
        """
        发布状态下去掉讨厌的日志显示
        """
        if self.settings.get('debug'):
            tornado.web.Application.log_request(self, handler)
        else:
            return


_unauthenticated_html = r'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>认证失败</title>
    <style>
        body {
            background-color: #729fcf;
        }

        article {
            width: 420px;
            margin: 160px auto 0 auto;
            padding: 20px;
            background-color: #fff;
            border: 1px solid #204a87;
            text-align: center;
        }

        h1 {
            font-size: 18px;
            margin: 0 0 20px 0;
            padding: 0;
        }

        p {
            margin: 0;
            padding: 0;
        }

        button {
            font-size: 13px;
            min-width: 80px;
            height: 22px;
            border: 1px solid #39f;
            border-radius: 10px;
            cursor: pointer;
            background-color: #fff;
        }

        button:hover {
            background-color: #9cf;
        }
    </style>
</head>
<body>
<article>
    <h1>请输入正确的用户名和密码</h1>

    <p>
        <button onclick="javascript:location.reload()">重试</button>
    </p>
</article>
</body>
</html>
'''

_unauthorized_html = r'''
<!DOCTYPE html>
<html>
<head>
    <title>鉴权失败</title>
    <style>
        body {
            background-color: #729fcf;
        }

        article {
            width: 420px;
            margin: 160px auto 0 auto;
            padding: 20px;
            background-color: #fff;
            border: 1px solid #204a87;
            text-align: center;
        }

        h1 {
            font-size: 18px;
            margin: 0 0 20px 0;
            padding: 0;
        }

        p {
            margin: 0;
            padding: 0;
        }

        button {
            font-size: 13px;
            min-width: 80px;
            height: 22px;
            border: 1px solid #39f;
            border-radius: 10px;
            cursor: pointer;
            background-color: #fff;
        }

        button:hover {
            background-color: #9cf;
        }
    </style>
</head>
<body>
<article>
    <h1>您没有权限访问当前页面</h1>

    <p>
        <button onclick="javascript:location.reload()">重试</button>
        <button onclick="javascript:history.back()">返回</button>
    </p>
</article>
</body>
</html>
'''