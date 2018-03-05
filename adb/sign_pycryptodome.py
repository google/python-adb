from adb import adb_protocol

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15


class PycryptodomeAuthSigner(adb_protocol.AuthSigner):

    def __init__(self, rsa_key_path=None):
        super(PycryptodomeAuthSigner, self).__init__()

        if rsa_key_path:
            with open(rsa_key_path + '.pub', 'rb') as rsa_pub_file:
                self.public_key = rsa_pub_file.read()

            with open(rsa_key_path, 'rb') as rsa_priv_file:
                self.rsa_key = RSA.import_key(rsa_priv_file.read())

    def Sign(self, data):
        h = SHA256.new(data)
        return pkcs1_15.new(self.rsa_key).sign(h)

    def GetPublicKey(self):
        return self.public_key
