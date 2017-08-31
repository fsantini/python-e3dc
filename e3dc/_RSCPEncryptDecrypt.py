from CryptoPlus.Cipher import python_Rijndael
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
    return string.ljust(newL, '\x00')

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
        
        self.key = key.ljust(KEY_SIZE,'\xff')
        self.encryptIV = '\xff' * BLOCK_SIZE
        self.decryptIV = '\xff' * BLOCK_SIZE
        self.remainingData = ''
        self.oldDecrypt = ''
        
    def encrypt(self, plainText):
        encryptor = python_Rijndael.new(self.key, python_Rijndael.MODE_CBC, self.encryptIV, blocksize = BLOCK_SIZE)
        encText = encryptor.encrypt(zeroPad_multiple(plainText, BLOCK_SIZE))
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
        if self.oldDecrypt != '':
            self.decryptIV = self.oldDecrypt[previouslyProcessedData - BLOCK_SIZE:previouslyProcessedData]
        
        self.oldDecrypt = encText # save current block
        
        toDecrypt = truncate_multiple(remainingData + encText, BLOCK_SIZE)
        decryptor = python_Rijndael.new(self.key, python_Rijndael.MODE_CBC, self.decryptIV, blocksize = BLOCK_SIZE)
        return decryptor.decrypt(toDecrypt).rstrip('\x00')
                                        
        
if __name__ == '__main__':
    ed = RSCPEncryptDecrypt("love")
    enc = ed.encrypt("hello")
    print (enc,)
    dec = ed.decrypt(enc)
    print (dec,)
    enc2 = ed.encrypt("hello")
    print (enc2,)
    dec2 = ed.decrypt(enc2)
    print (dec2,)
