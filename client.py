from arcwebsocket.common import FORBIDDEN_CLOSE_CODES
from arcwebsocket.common import WebSocketError, WebSocketFrame
import base64
import collections.abc
import hashlib
import io
import os
import socket
import ssl
import struct
import threading
import types
import urllib.parse


class WebSocketClient:
    @staticmethod
    def _frame(
        op: int,
        data: collections.abc.ByteString,
        final: bool
    ) -> WebSocketFrame:
        """
        Return a client frame with the given fields. The rest are set up
        automatically as appropriate for a frame sent by the client. Overriding
        this method to validate frames for extension protocols is valid. This
        is not done since the base protocol does not place restrictions on the
        content of individual frames.
        """
        
        return WebSocketFrame(final, (), op, True, data)


    def __init__(
        self,
        url: str,
        sock: socket.socket = None,
        secure: bool = None,
        protocol: str = None,
        version: int = 13
    ):
        """
        Initialize a client using a URL and optionally a connected socket. If
        secure not given, it is assumed based on the scheme if it is WS/S or
        HTTP/S, and based on the port otherwise. Protocol and version
        parameters given directly to server in handshake.
        
        If a socket given, it must already be connected, but the handshake must
        not be performed. A kept-alive socket used for earlier HTTP
        communication can be used.
        """
        
        self.addr = None
        """The remote address of the underlying socket."""
        self.connected = sock is not None
        """Whether the underlying socket is connected."""
        self.frameHandlers = [None] * 16
        """The callbacks for each frame type."""
        self.limits = self.__initLimits()
        """The various byte limits of the client."""
        self.messageHandlers = [None] * 8
        """The callbacks for each method type."""
        self.path = None
        """Path to GET in the handshake."""
        self.protocol = protocol
        """Which extension protocols to use."""
        self.secure = secure
        """Whether the TLS is being used."""
        self.url = url
        """The URL that was used to create the client."""
        self.version = version
        """WebSocket version to request, currently only 13 valid."""
        
        self._host = ''
        """The host name that will be used in the handshake."""
        self._message = []
        """The fragments of an incomplete message left over from reading."""
        self._messageLock = threading.Lock()
        """The lock that prevents interleaving data messages."""
        self._recvLock = threading.Lock()
        """The lock that prevents threads getting parts of the same message."""
        self._sendLock = threading.Lock()
        """The lock that prevens interleaving individual frames."""
        self._sock = sock
        """The socket that will be used for WebSocket communication."""
        self._statusLocal = -1
        """The close status chosen by the client."""
        self._statusRemote = -1
        """The close status chosen by the server."""
        self._tail = None
        """The incomplete frame leftover from a read on the socket."""
        
        self.messageHandlers[1] = self.__handleText
        self.messageHandlers[2] = self.__handleBytes
        self.frameHandlers[8] = self.__handleClose
        self.frameHandlers[9] = self.__handlePing
        self._host, port, self.path = self._parseUrl()
        self._sock, self.addr, self.secure = self.__initSock(port)


    def __connectSock(self):
        """
        Set up the socket buffers and connect it. Called by connect.
        """
        
        if not self.connected:
            if self.limits.netRecvBuf > 0:
                self._sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_RCVBUF,
                    self.limits.netRecvBuf
                )
            else:
                self.limits.netRecvBuf = self._sock.getsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_RCVBUF
                )
            if self.limits.frameLimit == -1:
                self.limits.frameLimit = self.limits.netRecvBuf
            if self.limits.messageLimit == -1:
                self.limits.messageLimit = self.limits.frameLimit
            if self.limits.netSendBuf > 0:
                self._sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_SNDBUF,
                    self.limits.netSendBuf
                )
            else:
                self.limits.netSendBuf = self._sock.getsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_SNDBUF
                )
            self._sock.connect(self.addr)
            self.connected = True


    def __getHttpResponse(self) -> collections.abc.Collection:
        """
        Loop over the socket to get the handshake response headers and return
        them. Whatever extra, non-header data came out of the socket goes in
        _tail.
        """
        
        headers = b''
        buffer = self._sock.recv(self.limits.netRecvBuf)
        while buffer != b'' and self._tail is None:
            headers += buffer
            if len(headers) > self.limits.headerLimit: return None
            if b'\r\n\r\n' in headers:
                headers, _, self._tail = headers.partition(b'\r\n\r\n')
            else:
                buffer = self._sock.recv(self.limits.netRecvBuf)
        if self._tail is None: return None
        headers = headers.decode('ASCII').split('\r\n')
        return headers


    def __handleBytes(self, message: list):
        """
        Return the plain payloads from the message fragments concatenated
        together.
        """
        
        message = b''.join(message)
        print('byte message: {} bytes'.format(len(bytes)))


    def __handleClose(self, frame: WebSocketFrame) -> bytes:
        """
        Return an error indicating the server requested a connection closure.
        """
        
        if frame.size >= 2:
            code = struct.unpack('>H', frame.payload[:2])[0]
        else:
            code = 1005
        self._statusRemote = code
        if self._statusLocal < 0:
            self._close(frame.payload)


    def __handlePing(self, frame: WebSocketFrame) -> bytes:
        """
        Send a pong frame with the given frame's payload to the server.
        """
        
        self._sendFrame(self._frame(10, frame.payload, True))


    def __handleText(self, message: list):
        """
        Decode the text in a message as UTF-8 and return it. Using a different
        text handler is expected to be the most important class feature.
        """
        
        try:
            message = b''.join(message).decode('UTF-8')
        except UnicodeDecodeError:
            raise WebSocketError(1007, 'invalid text message')
        print('text message: ' + message)


    def __initLimits(self) -> types.SimpleNamespace:
        """
        Set up the default byte limits for the client. Called by __init__. If
        netSendBuf or netRecvBuf are 0, don't change the default buffer sizes
        for sockets. If frameLimit is 0, there is no frame limit. If frameLimit
        is -1, it's the same as netRecvBuf. If headerLimit is 0, there is no
        header limit. messageLimit follows the same rules as frameLimit.
        """
        
        limits = types.SimpleNamespace()
        limits.fileBuf = io.DEFAULT_BUFFER_SIZE
        limits.frameLimit = -1
        limits.headerLimit = 65536
        limits.messageLimit = -1
        limits.netSendBuf = 0
        limits.netRecvBuf = 0
        return limits


    def __initSock(self, port) -> tuple:
        """
        Return socket to use, its remote address, and whether it uses TLS. If
        socket given, its connected address and whether it uses TLS returned.
        If not, address is looked up and secure parameter returned if given,
        otherwise secure is True if address port is 443 and False otherwise.
        Called by __init__.
        """
        
        if self._sock is None:
            family, _, _, _, addr = socket.getaddrinfo(self._host, port)[0]
            if self.secure is None:
                if addr[1] == 443: secure = True
                else: secure = False
            sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            if secure: sock = ssl.wrap_socket(sock)
        
        else:
            sock = self._sock
            addr = sock.getpeername()
            if hasattr(sock, 'ssl_version'): secure = True
            else: secure = False
            self.limits.netRecvBuf = sock.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_RCVBUF
            )
            self.limits.netSendBuf = sock.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_SNDBUF
            )
        
        return sock, addr, secure


    def __recvFrames(self) -> list:
        """
        Block until at least one data frame received or close handshake occurs,
        then return all data frames in the buffer. Raise an exception if the
        buffer exceeds limits.frameLimit bytes without a complete frame, if the
        connection closes, or if a masked frame received. Not thread-safe.
        """
        
        buffer = None
        frames = []
        limit = self.limits.frameLimit
        while buffer != self._tail:
            buffer = self._tail
            frame, self._tail = WebSocketFrame.decode(buffer)
            if frame is not None:
                if frame.op == 8 or self._statusLocal < 0:
                    frames.append(frame)
            elif len(frames) < 1:
                if limit != 0 and len(self._tail) > limit:
                    raise WebSocketError(1009, 'frame too big')
                buffer = self._sock.recv(self.limits.netRecvBuf)
                if len(buffer) < 1:
                    raise WebSocketError(1006, 'connection closed mid-frame')
                self._tail += buffer
                buffer = None
        return frames


    def __recvMessages(self):
        """
        Block until at least one message received, then handle a list of
        messages in the buffer. There's a lot of WebSocket-required error
        handling here. Frame handlers are called here, not in __recvFrames,
        because this ensures that frame handlers are called for each frame in
        a message followed immediately by that message's handler; nothing
        happens out of order. However, neither of these methods are thread-safe,
        while recv is.
        """
        
        fragmentType = 0
        handled = False
        messageSize = 0
        while not handled:
            for frame in self.__recvFrames():
                if frame.masked:
                    raise WebSocketError(1002, 'masked frame from server')
                if frame.op > 7 and not frame.final:
                    raise WebSocketError(1002, 'non-final control frame')
                if not frame.final:
                    if frame.op == 0 and fragmentType == 0:
                        raise WebSocketError(1002, 'early continuation frame')
                    elif frame.op != 0 and fragmentType != 0:
                        raise WebSocketError(1002, 'non-zero continuation op')
                    elif fragmentType == 0:
                        fragmentType = frame.op
                    messageSize += frame.size
                    if messageSize > self.limits.messageLimit:
                        raise WebSocketError(1009, 'message too long')
                    self._message.append(frame)
                elif frame.op > 7:
                    handler = self.frameHandlers[frame.op]
                    if handler is not None:
                        handler(frame)
                    if frame.op == 8:
                        return []
                else:
                    if fragmentType != 0 and frame.op != 0:
                        raise WebSocketError(1002, 'non-zero continuation op')
                    if fragmentType == 0 and frame.op == 0:
                        raise WebSocketError(1002, 'bad fragmentation')
                    fragmentType = max(frame.op, fragmentType)
                    handler = self.frameHandlers[fragmentType]
                    self._message.append(frame)
                    if handler is None:
                        message = [f.payload for f in self._message]
                    else:
                        message = [handler(f) for f in self._message]
                    handler = self.messageHandlers[fragmentType]
                    if handler is None:
                        raise WebSocketError(1003, 'unkown op')
                    handler(message)
                    handled = True
                    self._message.clear()
                    fragmentType = 0


    def __sendHttpRequest(self, extra: collections.abc.Iterable) -> str:
        """
        Send the needed WebSocket headers and any extra headers sought by
        extensions. If any of the extra headers have the same name as a reserved
        header, ignore it. This is to avoid mistakes, since the only 2 reserved
        headers that are useful to modify are already customizable by changing
        version and protocol. Also, giving control over the generation of the
        handshake key could violate its requirements.
        """
        
        reserved = (
            'host', 'connection', 'upgrade', 'sec-websocket-version',
            'sec-websocket-key', 'sec-websocket-protocol'
        )
        extra = ( (n, v) for n, v in extra if n.lower() not in reserved )
        headers = ['GET ' + self.path + ' HTTP/1.1']
        headers.extend('{}: {}'.format(n, v) for n, v in extra)
        headers.append('Host: ' + self._host + ':' + str(self.addr[1]))
        headers.append('Upgrade: WebSocket')
        headers.append('Connection: Upgrade')
        headers.append('Sec-WebSocket-Version: ' + str(self.version))
        if self.protocol is not None:
            headers.append('Sec-WebSocket-Protocol: ' + self.protocol)
        key = base64.b64encode(os.urandom(16))
        headers.append('Sec-WebSocket-Key: ' + key.decode('ASCII'))
        key = key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        key = base64.b64encode(hashlib.sha1(key).digest()).decode('ASCII')
        headers.append('')
        headers.append('')
        self._sock.sendall('\r\n'.join(headers).encode('ASCII'))
        return key


    def __verifyResponseHeaders(
        self,
        headers: collections.abc.Collection,
        key: str
    ) -> bool:
        """
        Validate the handshake response from the WebSocket server. There are
        only a few ways to fail, and the assumption in that case is that the
        server doesn't support WebSocket after all.
        """
        
        if headers[0].partition(' ')[2].partition(' ')[0] != '101':
            raise WebSocketError(1002, 'incorrect HTTP status code')
        headers = ( h.partition(': ') for h in headers[1:] )
        headers = {n.lower(): v for n, _, v in headers}
        if (
            'upgrade' not in headers or
            'connection' not in headers or
            'sec-websocket-accept' not in headers
        ): raise WebSocketError(1002, 'required response header missing')
        if (
            headers['connection'].lower() != 'upgrade' or
            headers['upgrade'].lower() != 'websocket' or
            headers['sec-websocket-accept'] != key
        ): raise WebSocketError(1002, 'invalid response header value')


    def _close(self, payload: bytes):
        """
        Perform the closing handshake then close the socket. This process is
        surprisingly complicated. Call this both after receiving a closing frame
        and when local code wants to initiate a close. This is thread-safe in a
        couple of ways. Once the client sends the close frame, it can't send
        more data frames, so _messageLock is acquired here. _frameLock is not,
        since sending control frames may still be needed in the middle of the
        closing handshake. _recvLock is grabbed depending on which side starts
        the closing process. Certain close codes forbidden by the standard
        result in a ValueError here. Closing synchronization means that a
        message currently being sent must wait to finish before closing
        progresses, but sending methods should handle this by checking
        connected.
        """
        
        self._messageLock.acquire()
        try:
            if not self.connected: return
            self.connected = False
            if len(payload) >= 2:
                code = struct.unpack('>H', payload[:2])[0]
            else:
                code = 1005
            self._statusLocal = code
            if self._statusRemote < 0 and code in FORBIDDEN_CLOSE_CODES:
                raise ValueError(str(code) + ' not allowed')
            self._sendFrame(self._frame(8, payload, True))
            if self._statusRemote < 0:
                self._recvLock.acquire()
                try:
                    self.__recvMessages()
                finally:
                    self._recvLock.release()
            self._sock.shutdown(socket.SHUT_WR)
            while len(self._sock.recv(self.limits.netRecvBuf)) > 0: pass
        finally:
            self.connected = False
            self._sock.close()
            self._messageLock.release()


    def _getAdditionalHeaders(self) -> collections.abc.Iterable:
        """
        Return an iterable of 2-tuples containing the headers to be sent during
        the handshake that aren't required by the base WebSocket protocol. The
        first value in each tuple is the header name and the second is the
        header value. All values are strings and empty values are forbidden.
        Override this to send additional headers as needed. Called by connect.
        """
        
        return ()


    def _parseUrl(self) -> tuple:
        """
        Parse the initial URL to retrieve host, port, and path. The port is
        assumed by scheme if not given. Since the GET command needs a path
        during the handshake, path is assumed to be / if not given. Called by
        __init__.
        """
        
        url = urllib.parse.urlparse(self.url)
        host = url.hostname
        path = url.path
        port = None
        if url.port is None:
            if url.scheme == 'ws' or url.scheme == 'http': port = 'http'
            elif url.scheme == 'wss' or url.scheme == 'https': port = 'https'
            else: port = 'unknown'
        else:
            port = url.port
        if path == '': path = '/'
        if host is None or port == 'unknown':
            raise ValueError('host: {} port: {}'.format(host, port))
        return host, port, path


    def _sendData(self, data: collections.abc.Sequence):
        """
        
        """
        
        if isinstance(data, str):
            data = data.encode('UTF-8')
            op = 1
        else:
            data = bytes(data)
            op = 2
        self._messageLock.acquire()
        try:
            if not self.connected: return
            self._sendFrame(self._frame(op, data, True))
        finally:
            self._messageLock.release()


    def _sendFrame(self, frame: WebSocketFrame):
        """
        Send a single frame to the server without validation. Thread-safe.
        """
        
        self._sendLock.acquire()
        try:
            self._sock.sendall(frame.encode())
        finally:
            self._sendLock.release()


    def _verifyExtendedHandshake(self, headers: collections.abc.Collection):
        """
        Verifies the response headers that aren't required by the base
        WebSocket protocol. Throws a WebSocketException if there's an issue.
        Override this to verify headers required by extensions. Called by 
        connect after verifying the headers minimally according to the standard.
        """
        
        return


    def close(self, reason: str):
        """
        Start a closing handshake using code 1001. Since the base protocol
        doesn't define an end of communication, this is the only code the client
        should send.
        """
        
        self._close(b'\03\xe9' + reason.encode('UTF-8'))


    def connect(self):
        """
        Start the WebSocket connection by connectin the socket and sending the
        handshake. After creating the client, set up its limits before calling
        this. If connection succeeds, don't use the socket for anything else. If
        connected socket given at object creation, keep in mind that the server
        may time out the connection if this function is called too late.
        """
        
        try:
            self.__connectSock()
            headers = self._getAdditionalHeaders()
            key = self.__sendHttpRequest(headers)
            headers = self.__getHttpResponse()
            if headers is None:
                raise WebSocketError(1002, 'invalid HTTP response')
            self.__verifyResponseHeaders(headers, key)
            self._verifyExtendedHandshake(headers)
        except:
            self.connected = False
            self._sock.close()
            raise


    def recv(self):
        """
        A basic wrapper for __recvMessages. Grab the recv lock for thread
        safety and catch WebSocket errors, closing the connection if one
        appears.
        """
        
        reason = None
        self._recvLock.acquire()
        try:
            if not self.connected: return
            self.__recvMessages()
        except WebSocketError as error:
            reason = error
        finally:
            self._recvLock.release()
        if reason is not None:
            error = reason
            reason = struct.pack('>H', error.code)
            reason += error.reason.encode('UTF-8')
            self._close(reason)
            raise error
