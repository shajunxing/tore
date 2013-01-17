# -*- coding: UTF-8 -*-

import base64
import copy
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
    RequestHandler, Loader and Template do some tuning to origin Tornado classes to support automatic code file loading
    """

    def create_template_loader(self, template_path):
        settings = self.application.settings
        if "template_loader" in settings:
            return settings["template_loader"]
        kwargs = {}
        if "autoescape" in settings:
            kwargs["autoescape"] = settings["autoescape"]

        # HERE IS THE MODIFICATION
        # load my own loader class
        return Loader(template_path, **kwargs)

    def write_html_file(self, path):
        """
        write html file back, path may be relative to "root_dir" or absolute
        used by 401, 403 error return
        """
        root_dir = self.application.settings.get('root_dir')
        self.set_header('Content-Type', 'text/html; charset=UTF-8')
        with open(os.path.join(root_dir, path), "rb") as file:
            self.write(file.read())

    def write_json_text(self, txt):
        """
        directly output Json text
        NOTICE: encoding and gramma will not be checked
        """
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        self.write(txt)

    def write_json_object(self, obj):
        """
        convert Python object to Json string
        """
        if self.application.settings.get('debug'):
            self.write_json_text(json.dumps(obj, indent=4, ensure_ascii=False))
        else:
            self.write_json_text(json.dumps(obj))

    def write_plain_text(self, txt):
        """
        write plain text
        NOTICE: text should be utf-8 encoded
        """
        self.set_header('Content-Type', 'text/plain; charset=UTF-8')
        self.write(txt)

    def write_exception(self, ex):
        """
        set 500 code and return exception description as string
        client can read this through xhr.responseText from error:function (xhr) {} from jQuery.ajax
        """
        self.set_status(500)
        self.write_plain_text(str(ex))

    def get_params_as_dict(self):
        """
        get dictionary wrapped request params
        """
        ret = {}
        for k in list(self.request.arguments.keys()):
            ret[k] = self.get_argument(k)
        return ret

    def get_body_as_text(self):
        """
        get text formatted requese body
        """
        return self.request.body.decode()

    def get_body_as_object(self):
        """
        convert Json string formatted request body to Python object
        """
        return json.loads(self.get_body_as_text())


class Loader(tornado.template.Loader):
    def _create_template(self, name):
        path = os.path.join(self.root, name)
        f = open(path, "rb")
        template_string = f.read()
        f.close()

        # HERE IS THE MODIFICATION
        # try to load code file
        try:
            f = open(path + '.py', "rb")
            source_string = f.read()
            f.close()
        except Exception:
            source_string = b''

        # load my own template class
        template = Template(template_string, source_string, name=name, loader=self)
        return template


class Template(tornado.template.Template):
    def __init__(self, template_string, source_string, name="<string>", loader=None,
                 compress_whitespace=None, autoescape=tornado.template._UNSET):
        # new parameter "source_string" is added which contains code file content
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

            # HERE IS THE MODIFICATION
            # attach code file content, from ancestor to self
            # template inheritance works perfectly
            for ancestor in ancestors:
                buffer.write('\n\n')
                buffer.write(ancestor.template.source_string)

            return buffer.getvalue()
        finally:
            buffer.close()

    def generate(self, **kwargs):
        # HERE IS THE MODIFICATION
        # debug output the final code generated by engine
        formatted_code = tornado.template._format_code(self.code).rstrip()
        logging.debug("%s code:\n%s", self.name, formatted_code)
        return tornado.template.Template.generate(self, **kwargs)


def authenticated(method):
    """
    decorator for HTTP basic authentication
    NOTICE: user name and password is set by this decorator, so you cannot get user name without it.
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
            #                logging.warning(ex)
                self._current_user = None

            if not self._current_user:
                self.set_header('WWW-Authenticate', 'Basic')
                self.set_status(401)
                filename = self.application.settings.get('unauthenticated_response_file')
                if filename:
                    self.write_html_file(filename)
                else:
                    self.write(b'Unauthenticated')
                return

        return method(self, *args, **kwargs)

    return wrapper


def authorized(method):
    """
    decorator to check whether a user can visit this url
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        authorization_method = self.settings.get('authorization')
        if authorization_method and not authorization_method(self.current_user, self.request.path):
            self.set_status(403)
            filename = self.application.settings.get('unauthorized_response_file')
            if filename:
                self.write_html_file(filename)
            else:
                self.write(b'Unauthorized')
            return

        return method(self, *args, **kwargs)

    return wrapper


class TemplateHandler(RequestHandler):
    """
    enhanced template handler
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
        goto get
        """
        self.get(*args, **kwargs)


class JsonHandler(RequestHandler):
    """
    Json handler (Deprecated)
    NOTICE: origin "write" method of RequestHandler only support json conversion of dict type, so limited
    """


class ForbiddenFileHandler(RequestHandler):
    def get(self, *args, **kwargs):
        """
        return 404 for cheating
        """
        raise tornado.web.HTTPError(404)


class Application(tornado.web.Application):
    """
    enhanced Application class used by tore.start_server()
    """

    def __init__(self, **settings):
        _settings = copy.deepcopy(settings)


        # root dir of the web application
        if not _settings.get('root_dir'):
            _settings['root_dir'] = os.getcwd()

        # root dir of template and static files
        _settings['web_root_dir'] = os.path.join(_settings['root_dir'], 'web')

        # used by TemplateHandler
        _settings['template_path'] = _settings['web_root_dir']

        _handlers = [
            # some default handlers
            ('/', tornado.web.RedirectHandler, dict(url='/web/index.t')),
            ('/web/(.*?\.t)', TemplateHandler),
            ('/web/.*?\.py', ForbiddenFileHandler),
            ('/web/(.*)', tornado.web.StaticFileHandler, dict(path=_settings.get('web_root_dir'))),
            # message service url
            ('/messaging', tore.messaging.WebSocketHandler)
        ]

        h = _settings.get('handlers')
        # in python, "[]" is considered to be false
        if h is not None:
            _handlers += h
            del _settings['handlers']

        tornado.web.Application.__init__(self, _handlers, **_settings)

    def log_request(self, handler):
        """
        get rid of logging output at release mode
        """
        if self.settings.get('debug'):
            tornado.web.Application.log_request(self, handler)
        else:
            return
