import pytest
from mock import Mock

from hamiltonmicrolab.commands.instrument_status_request import (
    InstrumentBusyStatus,
    InstrumentByteStatus,
    InstrumentErrorRequest,
    InstrumentErrorStatus,
    InstrumentStatusRequest,
    TimerStatus,
)
from tests.commsstub import CommsStub, comms_patch


class TestInstrumentStatusRequest:
    def test_timer_status_request_failure(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (False, "")

        address = "d"

        timer_status = TimerStatus(CommsStub())
        timer_status._log = logger_mock = Mock()

        timer_busy = timer_status.request(address)

        assert timer_busy is None
        send_receive_mock.assert_called_once_with(address + "E3")
        assert (
            "Unable to carry out timer request" in logger_mock.error.call_args.args[0]
        )

    def test_timer_status_request_reports_busy(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (True, "A")

        timer_status = TimerStatus(CommsStub())
        timer_status._log = logger_mock = Mock()

        timer_busy = timer_status.request()

        assert timer_busy
        assert "Timer is busy" in logger_mock.info.call_args.args[0]

    def test_timer_status_request_reports_not_busy(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (True, "@")

        timer_status = TimerStatus(CommsStub())
        timer_status._log = logger_mock = Mock()

        timer_busy = timer_status.request()

        assert not timer_busy
        assert "Timer is not busy" in logger_mock.info.call_args.args[0]

    def test_instrument_byte_status_failure(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (False, "")

        request_name = "a type of request"
        instrument_status = InstrumentByteStatus(CommsStub(), "", request_name, [])
        instrument_status._log = logger_mock = Mock()

        assert not instrument_status.request()
        assert (
            f"Unable to carry out {request_name}" in logger_mock.error.call_args.args[0]
        )

    def test_instrument_byte_status_message(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (True, "G")

        # G = 01000111 so second string and last three strings should be logged provided
        # they're nonempty
        response_map = [
            "",
            "",
            "",
            "",
            "don't print",
            "do print a",
            "do print b",
            "do print c",
        ]

        instrument_status = InstrumentByteStatus(CommsStub(), "", "", response_map)
        instrument_status._log = logger_mock = Mock()

        assert instrument_status.request() == 0b1000111

        for response in response_map[-3:]:
            assert response in logger_mock.info.call_args.args[0]

        assert "don't print" not in logger_mock.info.call_args.args[0]

    def test_instrument_error_request_reports_no_errors(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (True, "@@@@")

        instrument_error_request = InstrumentErrorRequest(CommsStub())
        instrument_error_request._log = logger_mock = Mock()

        instrument_error_request.request()

        for arg in logger_mock.info.call_args.args:
            assert "No known errors" in arg

    @pytest.mark.parametrize(
        "index,component_name",
        [
            (0, "Left syringes"),
            (1, "Left valves"),
            (2, "Right syringes"),
            (3, "Right valves"),
        ],
    )
    def test_single_component_has_not_initialised_error(
        self, mocker, index, component_name
    ):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")

        response = "@@@@"
        temp = list(response)
        temp[index] = "A"
        response = "".join(temp)

        send_receive_mock.return_value = (True, response)

        instrument_error_request = InstrumentErrorRequest(CommsStub())
        instrument_error_request._log = logger_mock = Mock()

        response = [64, 64, 64, 64]
        response[index] = 65

        assert instrument_error_request.request() == tuple(response)

        for i in range(4):
            if i == index:
                assert "not initialised" in logger_mock.info.mock_calls[i].args[0]
            else:
                assert "not initialised" not in logger_mock.info.mock_calls[i].args[0]

        assert component_name in logger_mock.info.mock_calls[index].args[0]

    def test_instrument_error_request_failure(self, mocker):
        send_receive_mock = mocker.patch(f"{comms_patch}.Comms.send_receive")
        send_receive_mock.return_value = (False, "")

        instrument_error_request = InstrumentErrorRequest(CommsStub())
        instrument_error_request._log = logger_mock = Mock()

        assert instrument_error_request.request() is None
        assert (
            f"Unable to carry out instrument error request"
            in logger_mock.error.call_args.args[0]
        )

    def test_instrument_error_request_members(self, mocker):
        instrument_error_request = InstrumentErrorRequest(CommsStub())
        assert instrument_error_request._request_string == "E2"
        assert instrument_error_request._syringes_response_map == [
            "",
            "",
            "",
            "do not exist",
            "initialisation error",
            "stroke too large",
            "overload error",
            "not initialised",
        ]
        assert instrument_error_request._valves_response_map == [
            "",
            "",
            "",
            "do not exist",
            "",
            "overload error",
            "initialisation error",
            "not initialised",
        ]

    def test_instrument_error_status_members(self, mocker):
        instrument_error_status = InstrumentErrorStatus(CommsStub())
        assert instrument_error_status._request_string == "T2"
        assert instrument_error_status._response_map == [
            "",
            "",
            "",
            "",
            "Right syringe error",
            "Right valve error",
            "Left syringe error",
            "Left valve error",
        ]

    def test_instrument_busy_status_members(self, mocker):
        instrument_busy_status = InstrumentBusyStatus(CommsStub())
        assert instrument_busy_status._request_string == "T1"
        assert instrument_busy_status._response_map == [
            "",
            "",
            "Handprobe/Foot switch active",
            "Prime/Step active",
            "Right syringe busy",
            "Right valve busy",
            "Left syringe busy",
            "Left valve busy",
        ]

    def test_instrument_status_request_members(self, mocker):
        instrument_status_request = InstrumentStatusRequest(CommsStub())
        assert instrument_status_request._request_string == "E1"
        assert instrument_status_request._response_map == [
            "",
            "",
            "",
            "Instrument error (valve or syringe error)",
            "Syntax error",
            "Valve drive(s) busy",
            "Syringe drive(s) busy",
            "Instrument idle, command buffer is not empty",
        ]

