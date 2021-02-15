import logging
import socket
import threading
from typing import Optional, Tuple, Union

# Constants
CR = "\r"
ACK = "\x06"
NACK = "\x21"
CODEC = "ascii"
TIMEOUT = 1.0  # Seconds
RECV_BUFFER = 4096  # Bytes


class Comms:
    def __init__(self, ip: str, port: int):

        self._log = logging.getLogger(self.__class__.__name__)
        logging.basicConfig(level=logging.DEBUG)

        self._endpoint = (ip, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(TIMEOUT)
        self._lock = threading.Lock()

    def connect(self):

        self._log.info(f"Connecting to {self._endpoint[0]}:{self._endpoint[1]}")
        self._socket.connect(self._endpoint)
        # Clear initial connection messages
        # TODO: Are these useful? Use as confirmation of connection?
        # self._clear_socket()
        self.clear_socket()

    def disconnect(self):
        self._socket.close()

    def clear_socket(self):
        """Read from socket until we timeout"""
        while True:
            try:
                self._socket.recv(RECV_BUFFER)
            except socket.timeout:
                break

    @staticmethod
    def _format_message(message: Union[str, bytes]) -> str:
        """Format message for printing by replacing ACK and CR bytes.

        Args:
            message (Union[str, bytes]): The message to format.

        Returns:
            str: The formatted message.
        """
        return str(message).replace(ACK, "<ACK>").replace(CR, "<CR>")

    def _send(self, request: str):
        """Send a request.

        Args:
            request (str): The request string to send.
        """
        request += CR
        self._log.debug(f"Sending request:\n{self._format_message(request)}")
        bytes_sent = self._socket.send(request.encode(CODEC))
        self._log.debug(f"Sent {bytes_sent} byte(s)")

    def _send_receive(self, request: str) -> Optional[str]:
        """Sends a request and attempts to decode the response. Does not determine if
        the response indicates acknowledgement from the device.

        Args:
            request (str): The request string to send.

        Returns:
            Optional[str]: If the response could be decoded and didn't contain NACK,
            then it is returned. Otherwise None is returned.
        """
        with self._lock:
            self._send(request)
            response = self._socket.recv(RECV_BUFFER)

        try:
            decoded_response = response.decode(CODEC)
        except UnicodeDecodeError:
            self._log.error(
                f"Failed to parse response as ascii:\n{self._format_message(response)}"
            )
            return None

        if decoded_response[0] == NACK:
            self._log.error("Received NACK")
            return None

        self._log.debug(f"Received response:\n{self._format_message(decoded_response)}")
        return decoded_response

    def send_receive(self, request: str) -> Tuple[bool, Optional[str]]:
        """Sends a request and attempts to decode the response. Determines if the
        response indicates acknowledgement from the device.

        Args:
            request (str): The request string to send.

        Returns:
            Tuple[bool, Optional[str]]: A tuple containing the request outcome and the
            response if one could be retrieved. The bool is True if the response was
            successful and False otherwise. The string contains the response if the
            request was successful, otherwise None is returned.
        """
        success = False
        data = None

        decoded_response = self._send_receive(request)
        if decoded_response is None:
            return False, None

        messages = decoded_response.split(CR)[:-1]

        if len(messages) > 1:
            self._log.warning(
                "Received multiple messages in response:\n"
                f"{self._format_message(decoded_response)}"
            )

        decoded_response = messages[-1]
        if decoded_response[0] == ACK:
            success = True
            data = decoded_response.strip(ACK).strip(CR) or None

        return success, data

    def send_auto_address_message(self) -> Optional[str]:
        """Sends the auto address message.

        Returns:
            Optional[str]: The response from the auto address request, or None if the
            auto-addressing failed.
        """
        decoded_response = self._send_receive("1a")
        if not decoded_response:
            return None
        return decoded_response.split(CR)[0]

