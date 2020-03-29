from py3rijndael import RijndaelCbc, ZeroPadding

import math

KEY_SIZE = 32
BLOCK_SIZE = 32

class ParameterError(Exception):
    pass

def zeroPad_multiple(string, value):
    l = len(string)
    if l % value == 0:
        return string
    newL = int(value * math.ceil(float(l)/value))
    return string.ljust(newL, b'\x00')

def truncate_multiple(string, value):
    l = len(string)
    if l % value == 0:
        return string
    newL = int(value * math.floor(float(l)/value))
    return string[:newL]

class RSCPEncryptDecrypt:
    def __init__(self, key):
        if len(key) > KEY_SIZE:
            raise ParameterError("Key must be <%d bytes" % (KEY_SIZE))
        
        self.key = key.ljust(KEY_SIZE,b'\xff')
        self.encryptIV = b'\xff' * BLOCK_SIZE
        self.decryptIV = b'\xff' * BLOCK_SIZE
        self.remainingData = b''
        self.oldDecrypt = b''
        
    def encrypt(self, plainText):
        encryptor = RijndaelCbc(self.key, self.encryptIV, padding=ZeroPadding(BLOCK_SIZE), block_size = BLOCK_SIZE)
        encText = encryptor.encrypt( plainText )
        self.encryptIV = encText[-BLOCK_SIZE:]
        return encText
        
    def decrypt(self, encText, previouslyProcessedData = None):
        if previouslyProcessedData is None:
            l = len(self.oldDecrypt)
            if l % BLOCK_SIZE == 0:
                previouslyProcessedData = l
            else:
                previouslyProcessedData = int(BLOCK_SIZE * math.floor(l/BLOCK_SIZE))
            
        #print previouslyProcessedData
        # previouslyProcessedData was passed by the parent: it means that a frame was decoded and there was some data left. This does not include the padding zeros
        if previouslyProcessedData % BLOCK_SIZE != 0:
            previouslyProcessedData = int(BLOCK_SIZE * math.ceil(previouslyProcessedData/BLOCK_SIZE))
            
        remainingData = self.oldDecrypt[previouslyProcessedData:]
        if self.oldDecrypt != b'':
            self.decryptIV = self.oldDecrypt[previouslyProcessedData - BLOCK_SIZE:previouslyProcessedData]
        
        self.oldDecrypt = encText # save current block
        
        toDecrypt = truncate_multiple(remainingData + encText, BLOCK_SIZE)
        decryptor = RijndaelCbc(self.key, self.decryptIV, padding=ZeroPadding(BLOCK_SIZE), block_size = BLOCK_SIZE)
        return decryptor.decrypt(toDecrypt)
                                        
        
if __name__ == '__main__':
    ed = RSCPEncryptDecrypt(b"love")
    enc = ed.encrypt(b"hello")
    print(enc)
    dec = ed.decrypt(enc)
    print(dec)
    enc2 = ed.encrypt(b"hello")
    print(enc2)
    dec2 = ed.decrypt(enc2)
    print(dec2)
