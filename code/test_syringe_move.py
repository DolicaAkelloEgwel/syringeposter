from mock import patch
from pytest import raises

from hamiltonmicrolab.commands.side import Side
from hamiltonmicrolab.commands.syringe_move import (
    SyringeAbsoluteMove,
    SyringeDispense,
    SyringePickup,
)

logging_path = "hamiltonmicrolab.commands.syringe_move.logging.getLogger"


class TestSyringeMove:
    def test_syringe_pickup_string_has_expected_value(self):
        pickup = 3
        speed = 20
        return_steps = 40
        syringe_pickup = SyringePickup(
            Side.RIGHT, value=pickup, speed=speed, return_steps=return_steps
        )
        assert syringe_pickup.string == Side.RIGHT.value + "P" + str(
            pickup
        ) + "S" + str(speed) + "N" + str(return_steps)

    def test_syringe_dispense_string_has_expected_value(self):
        dispense = 3
        syringe_dispense = SyringeDispense(Side.LEFT, dispense)
        assert syringe_dispense.string == Side.LEFT.value + "D" + str(dispense)

    def test_syringe_absolute_move_string_has_expected_value(self):
        absolute_move = 3
        syringe_absolute_move = SyringeAbsoluteMove(Side.LEFT, absolute_move)
        assert syringe_absolute_move.string == Side.LEFT.value + "M" + str(
            absolute_move
        )

    def test_invalid_syringe_move_value_raises_exception(self):
        with patch(logging_path) as get_logger:
            logger_mock = get_logger.return_value
            with raises(ValueError):
                SyringePickup(Side.RIGHT, value=-20)
            assert "outside acceptable range" in logger_mock.debug.call_args.args[0]
            assert "syringe pickup" in logger_mock.debug.call_args.args[0]

    def test_invalid_syringe_speed_value_raises_exception(self):
        with patch(logging_path) as get_logger:
            logger_mock = get_logger.return_value
            with raises(ValueError):
                SyringePickup(side=Side.RIGHT, value=20, speed=-300)
            assert "outside acceptable range" in logger_mock.debug.call_args.args[0]
            assert "speed" in logger_mock.debug.call_args.args[0]

    def test_invalid_syringe_return_steps_value_raises_exception(self):
        with patch(logging_path) as get_logger:
            logger_mock = get_logger.return_value
            with raises(ValueError):
                SyringePickup(side=Side.RIGHT, value=20, return_steps=-300)
            assert "outside acceptable range" in logger_mock.debug.call_args.args[0]
            assert "return steps" in logger_mock.debug.call_args.args[0]

    def test_noninteger_speed_creates_log_message(self):
        with patch(logging_path) as get_logger:
            logger_mock = get_logger.return_value
            bad_speed = 50.0
            SyringePickup(side=Side.RIGHT, value=20, speed=bad_speed)
            logger_mock.debug.assert_called_once_with(
                f"Ignoring non-integer speed argument of syringe move: {bad_speed}"
            )

    def test_noninteger_return_steps_creates_log_message(self):
        with patch(logging_path) as get_logger:
            logger_mock = get_logger.return_value
            bad_return_steps = 50.0
            SyringePickup(side=Side.RIGHT, value=20, return_steps=bad_return_steps)
            logger_mock.debug.assert_called_once_with(
                "Ignoring non-integer return steps argument of syringe move: "
                f"{bad_return_steps}"
            )

