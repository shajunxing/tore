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