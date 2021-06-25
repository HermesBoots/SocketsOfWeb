import collections.abc
import itertools
import os
import struct


FORBIDDEN_CLOSE_CODES = (1005, 1006, 1015)


class WebSocketError (ConnectionError):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        ConnectionError.__init__(self, code, reason)


class WebSocketFrame:
    def __init__(
        self,
        final: bool,
        reserved: collections.abc.Collection,
        op: int,
        masked: bool,
        payload: collections.abc.ByteString
    ):
        self.final = final
        """Whether this frame is the last one in the message."""
        self.reserved = reserved
        """Bits reserved for extensions."""
        self.op = op
        """Operation code."""
        self.masked = masked
        """Whether this frame's data is masked."""
        self.size = len(payload)
        """Length of the frame's data."""
        self.payload = payload
        """Frame payload."""
        self._str = None
        """The string version of this frame. Rarely used."""
        
        if self.size > 0x7FFFFFFFFFFFFFFF:
            raise ValueError(str(self.size) + ' too big')
        
        return


    def __len__(self) -> int:
        return self.size


    def __repr__(self) -> str:
        ret = 'WebSocketFrame('
        if self.op > 0: ret += 'op: ' + str(self.op) + ', '
        ret += 'len: ' + str(self.size) + ', '
        data = zip(self.payload, range(8))
        ret += ' '.join('{:02x}'.format(byte) for byte, _ in data)
        if self.size > 8: ret += '...'
        return ret
    
    
    def __str__(self) -> str:
        if self.final and self.op == 1:
            if self._str is None:
                self._str = self.payload.decode('UTF-8')
            return self._str
        else:
            return str(self.payload)
        

    @staticmethod
    def decode(buffer: collections.abc.ByteString) -> tuple:
        offset = 0
        
        if len(buffer) < offset + 1: return None, buffer
        
        # FIN
        final = bool(buffer[offset] & 0x80)
        
        # RSV
        reserved = ( bool(buffer[offset] & 1 << 6 - i) for i in range(3) )
        reserved = list(reserved)
        
        # OPCODE
        op = buffer[offset] & 0x0F
        
        offset += 1
        if len(buffer) < offset + 1: return None, buffer
        
        # MASKED
        masked = bool(buffer[offset] & 0x80)
        
        # PAYLOAD-LENGTH
        size = buffer[offset] & 0x7F
        offset += 1
        if size == 126:
            if len(buffer) < offset + 2: return None, buffer
            size = struct.unpack('>H', buffer[offset:offset+2])[0]
            offset += 2
        elif size == 127:
            if len(buffer) < offset + 8: return None, buffer
            size = struct.unpack('>Q', buffer[offset:offset+2])[0]
        
        # MASKING-KEY
        if masked:
            if len(buffer) < offset + 4: return None, buffer
            key = buffer[offset:offset+4]
            offset += 4
            
        if len(buffer) < offset + size: return None, buffer
        
        # PAYLOAD-DATA
        data = buffer[offset:offset+size]
        
        # MASKED-APPLICATION-DATA
        if masked:
            data = zip(data, itertools.cycle(key))
            data = bytes(byte ^ mask for byte, mask in data)
            
        offset += size
        frame = WebSocketFrame(final, reserved, op, masked, data)
        return frame, buffer[offset:]


    def encode(self) -> bytes:
        frame = bytearray()
        
        # FIN
        byte = int(self.final) << 7
        
        # RSV
        for i in range(min(3, len(self.reserved))):
            byte |= int(self.reserved[i]) << ( 6 - i )

        # OPCODE
        byte |= self.op
        
        frame.append(byte)
        
        # MASKED
        byte = bytearray((int(self.masked) << 7,))
        
        # PAYLOAD-LENGTH
        if self.size < 126:
            byte[0] |= self.size
        elif self.size < 65536:
            byte[0] |= 126
            byte.extend(bytearray(struct.pack('>H', self.size)))
        else:
            byte[0] |= 127
            byte.extend(bytearray(struct.pack('>Q', self.size)))
            
        frame.extend(byte)
        
        if self.masked:
            
            # MASKING-KEY
            key = bytearray(os.urandom(4))
            frame.extend(key)
            
            # MASKED-APPLICATION-DATA
            data = zip(self.payload, itertools.cycle(key))
            data = ( byte ^ mask for byte, mask in data )
        
        else:
            
            # UNMASKED-APPLICATION-DATA
            data = self.payload
            
        frame.extend(bytearray(data))
        return bytes(frame)
    
