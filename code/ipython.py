from IPython import embed

from hamiltonmicrolab.commands.command import Command
from hamiltonmicrolab.commands.side import Side
from hamiltonmicrolab.commands.syringe_move import (
    MAX_SYRINGE_MOVE,
    MIN_SYRINGE_MOVE,
    SyringeAbsoluteMove,
    SyringeDispense,
    SyringePickup,
)
from hamiltonmicrolab.commands.timer_delay import TimerDelay
from hamiltonmicrolab.commands.valve_position import (
    ValveToDefaultInput,
    ValveToDefaultOutput,
    ValveToDefaultWash,
)
from hamiltonmicrolab.microlab import Microlab


def enter_embed(microlab: Microlab):
    def move_syringe(side, val):
        a = [SyringeAbsoluteMove(side=side, value=val, speed=4)]
        microlab.send_command(Command(a))

    def move_left_syringe(val):
        move_syringe(Side.LEFT, val)

    def move_right_syringe(val):
        move_syringe(Side.RIGHT, val)

    def equilibrium():

        slow = 60
        fast = 2

        empty_right_subcommands = [
            SyringeDispense(side=Side.RIGHT, value=MAX_SYRINGE_MOVE - 1, speed=fast),
            SyringePickup(side=Side.LEFT, value=MAX_SYRINGE_MOVE - 1, speed=fast),
        ]
        empty_left_subcommands = [
            SyringeDispense(side=Side.LEFT, value=MAX_SYRINGE_MOVE - 1, speed=slow),
            SyringePickup(side=Side.RIGHT, value=MAX_SYRINGE_MOVE - 1, speed=slow),
        ]

        # initial position: R syringe full and L syringe empty
        move_right_syringe(MIN_SYRINGE_MOVE)
        move_left_syringe(MAX_SYRINGE_MOVE)
        # equilibrium movements
        microlab.cycle_commands(
            [Command(empty_right_subcommands), Command(empty_left_subcommands)]
        )

    def errors():
        microlab.instrument_done.request()
        microlab.instrument_error_request.request()
        microlab.instrument_error_status.request()

    embed()
    microlab.disconnect()

