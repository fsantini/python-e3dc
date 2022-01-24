import math

from py3rijndael import RijndaelCbc, ZeroPadding

KEY_SIZE = 32
BLOCK_SIZE = 32


class ParameterError(Exception):
    """Class for Parameter Error Exception."""

    pass


def zeroPad_multiple(string, value):
    """Zero padding string."""
    length = len(string)
    if length % value == 0:
        return string
    newL = int(value * math.ceil(float(length) / value))
    return string.ljust(newL, b"\x00")


def truncate_multiple(string, value):
    """Truncating sting."""
    length = len(string)
    if length % value == 0:
        return string
    newL = int(value * math.floor(float(length) / value))
    return string[:newL]


class RSCPEncryptDecrypt:
    """A class for encrypting and decrypting RSCP data."""

    def __init__(self, key):
        """Constructor of a RSCP encryption and decryption class.

        Args:
            key (str): RSCP encryption key
        """
        if len(key) > KEY_SIZE:
            raise ParameterError("Key must be <%d bytes" % (KEY_SIZE))

        self.key = key.ljust(KEY_SIZE, b"\xff")
        self.encryptIV = b"\xff" * BLOCK_SIZE
        self.decryptIV = b"\xff" * BLOCK_SIZE
        self.remainingData = b""
        self.oldDecrypt = b""

    def encrypt(self, plainText):
        """Method to encryt plain text."""
        encryptor = RijndaelCbc(
            self.key,
            self.encryptIV,
            padding=ZeroPadding(BLOCK_SIZE),
            block_size=BLOCK_SIZE,
        )
        encText = encryptor.encrypt(plainText)
        self.encryptIV = encText[-BLOCK_SIZE:]
        return encText

    def decrypt(self, encText, previouslyProcessedData=None):
        """Method to decryt encrypted text."""
        if previouslyProcessedData is None:
            length = len(self.oldDecrypt)
            if length % BLOCK_SIZE == 0:
                previouslyProcessedData = length
            else:
                previouslyProcessedData = int(
                    BLOCK_SIZE * math.floor(length / BLOCK_SIZE)
                )

        # previouslyProcessedData was passed by the parent: it means that a frame was decoded and there was some data left. This does not include the padding zeros
        if previouslyProcessedData % BLOCK_SIZE != 0:
            previouslyProcessedData = int(
                BLOCK_SIZE * math.ceil(previouslyProcessedData / BLOCK_SIZE)
            )

        remainingData = self.oldDecrypt[previouslyProcessedData:]
        if self.oldDecrypt != b"":
            self.decryptIV = self.oldDecrypt[
                previouslyProcessedData - BLOCK_SIZE : previouslyProcessedData
            ]

        self.oldDecrypt = encText  # save current block

        toDecrypt = truncate_multiple(remainingData + encText, BLOCK_SIZE)
        decryptor = RijndaelCbc(
            self.key,
            self.decryptIV,
            padding=ZeroPadding(BLOCK_SIZE),
            block_size=BLOCK_SIZE,
        )
        return decryptor.decrypt(toDecrypt)
