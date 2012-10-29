<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Example 3</title>
    <script src="jquery.js"></script>
    <script src="jquery.messaging.js"></script>
    <script>
        $(function () {
            $.getJSON('/system', null, function (info) {
                $('#username').html(info['username']);
                $('#platform').html(info['platform']);
                $('#processor').html(info['processor']);
            });

            var client = $.messageClient();
            client.onOpen(function () {
                client.subscribe("/time", function (time) {
                    $('#time').html(time);
                });
            });
        });
    </script>
</head>
<body>

<h1>Values from template</h1>

<p>Username: {{ current_user }}</p>

<p>Platform: {{ get_platform() }}</p>

<p>Processor: {{ platform.processor() }}</p>

<h1>Values from Ajax</h1>

<p>Username: <span id="username"></span></p>

<p>Platform: <span id="platform"></span></p>

<p>Processor: <span id="processor"></span></p>

<h1>Values from message</h1>

<p>Time: <span id="time"></span></p>
</body>
</html>