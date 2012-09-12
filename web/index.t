<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Sample Page</title>
    <link rel="icon" href="logo.png">
    <link rel="stylesheet" href="index.css">
    <script src="jquery.js"></script>
    <script src="jquery.messaging.js"></script>
    <script src="index.js"></script>
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