from trezor import ui, wire
from trezor.messages import ButtonRequestType
from trezor.messages.ButtonAck import ButtonAck
from trezor.messages.ButtonRequest import ButtonRequest
from trezor.ui.info import InfoConfirm
from trezor.ui.text import Text
from trezor.ui.word_select import WordSelector

from .bip39_keyboard import Bip39Keyboard
from .recover import RecoveryAborted
from .slip39_keyboard import Slip39Keyboard

from apps.common import mnemonic, storage
from apps.common.confirm import confirm, require_confirm
from apps.common.layout import show_success, show_warning
from apps.management.recovery_device import recovery_homescreen

if __debug__:
    from apps.debug import input_signal, confirm_signal


async def confirm_abort(ctx: wire.Context, dry_run: bool = False) -> bool:
    if dry_run:
        text = Text("Abort seed check", ui.ICON_WIPE)
        text.normal("Do you really want to", "abort the seed check?")
    else:
        text = Text("Abort recovery", ui.ICON_WIPE)
        text.normal("Do you really want to", "abort the recovery", "process?")
        text.bold("All progress will be lost.")
    return await confirm(ctx, text)


async def request_word_count(ctx: wire.Context, dry_run: bool) -> int:
    await ctx.call(ButtonRequest(code=ButtonRequestType.MnemonicWordCount), ButtonAck)

    if dry_run:
        text = Text("Seed check", ui.ICON_RECOVERY)
    else:
        text = Text("Wallet recovery", ui.ICON_RECOVERY)
    text.normal("Number of words?")

    if __debug__:
        count = await ctx.wait(WordSelector(text), input_signal)
        count = int(count)  # if input_signal was triggered, count is a string
    else:
        count = await ctx.wait(WordSelector(text))

    return count


async def request_mnemonic(ctx: wire.Context, count: int, mnemonic_type: int) -> str:
    await ctx.call(ButtonRequest(code=ButtonRequestType.MnemonicInput), ButtonAck)

    words = []
    for i in range(count):
        if mnemonic_type == mnemonic.TYPE_SLIP39:
            keyboard = Slip39Keyboard("Type word %s of %s:" % (i + 1, count))
        else:
            keyboard = Bip39Keyboard("Type word %s of %s:" % (i + 1, count))
        if __debug__:
            word = await ctx.wait(keyboard, input_signal)
        else:
            word = await ctx.wait(keyboard)

        # TODO: how was it with the kittens, UI and storage?
        mnemonics = storage.device.slip39.slip39_mnemonics.fetch()
        if mnemonic.TYPE_SLIP39 and len(mnemonics) > 0 and i < 4:
            for share in mnemonics:
                share_list = share.split(" ")
                # check if first 3 words of mnemonic match
                if i < 3:
                    if share_list[i] != word:
                        await show_identifier_mismatch(ctx)
                        # TODO: review is this the proper way to restart the workflow?
                        return await recovery_homescreen()
                # check if the fourth word is different from previous shares
                if i == 3:
                    if share_list[i] == word:
                        await show_share_already_added(ctx)
                        return await recovery_homescreen()
        words.append(word)

    return " ".join(words)


async def show_dry_run_result(ctx: wire.Context, result: bool) -> None:
    if result:
        await show_success(
            ctx,
            (
                "The entered recovery seed",
                "is valid and matches",
                "the one in the device.",
            ),
        )
    else:
        await show_warning(
            ctx,
            (
                "The entered recovery seed",
                "is valid but does not match",
                "the one in the device.",
            ),
        )


async def show_dry_run_different_type(ctx: wire.Context) -> None:
    text = Text("Dry run failure", ui.ICON_CANCEL)
    text.normal("Seed in the device was")
    text.normal("created using another")
    text.normal("backup mechanism.")
    await require_confirm(
        ctx, text, ButtonRequestType.ProtectCall, cancel=None, confirm="Continue"
    )


async def show_keyboard_info(ctx: wire.Context) -> None:
    await ctx.call(ButtonRequest(code=ButtonRequestType.Other), ButtonAck)

    info = InfoConfirm(
        "Did you know? "
        "You can type the letters "
        "one by one or use it like "
        "a T9 keyboard.",
        "Great!",
    )
    if __debug__:
        await ctx.wait(info, confirm_signal)
    else:
        await ctx.wait(info)


async def show_invalid_mnemonic(ctx, mnemonic_type: int):
    if mnemonic_type == mnemonic.TYPE_SLIP39:
        await show_warning(
            ctx,
            ("You have entered", "a recovery share", "that is not valid."),
            button="Try again",
        )
    else:
        await show_warning(
            ctx,
            ("You have entered", "a recovery seed", "that is not valid."),
            button="Try again",
        )


async def show_share_already_added(ctx):
    return await show_warning(
        ctx,
        ("Share already entered", "please enter", "a different share"),
        button="Try again",
    )


async def show_identifier_mismatch(ctx):
    return await show_warning(
        ctx,
        ("You have entered", "a share from another", "Shamir Backup"),
        button="Try again",
    )


class RecoveryHomescreen(ui.Control):
    def __init__(self, text: str, subtext: str = None):
        self.text = text
        self.subtext = subtext
        self.dry_run = storage.device.is_recovery_dry_run()
        self.repaint = True

    def on_render(self):
        if not self.repaint:
            return

        if self.dry_run:
            heading = "SEED CHECK"
        else:
            heading = "RECOVERY MODE"
        ui.header_warning(heading, clear=False)

        if not self.subtext:
            ui.display.text_center(ui.WIDTH // 2, 80, self.text, ui.BOLD, ui.FG, ui.BG)
        else:
            ui.display.text_center(ui.WIDTH // 2, 65, self.text, ui.BOLD, ui.FG, ui.BG)
            ui.display.text_center(
                ui.WIDTH // 2, 92, self.subtext, ui.NORMAL, ui.FG, ui.BG
            )

        ui.display.text_center(
            ui.WIDTH // 2, 130, "It is safe to eject Trezor", ui.NORMAL, ui.GREY, ui.BG
        )
        ui.display.text_center(
            ui.WIDTH // 2, 155, "and continue later", ui.NORMAL, ui.GREY, ui.BG
        )

        self.repaint = False


async def homescreen_dialog(
    ctx: wire.DummyContext, homepage: RecoveryHomescreen, button_label: str
) -> None:
    while True:
        continue_recovery = await confirm(
            ctx, homepage, confirm=button_label, major_confirm=True
        )
        if continue_recovery:
            # go forward in the recovery process
            break
        # user has chosen to abort, confirm the choice
        dry_run = storage.device.is_recovery_dry_run()
        if await confirm_abort(ctx, dry_run):
            raise RecoveryAborted
