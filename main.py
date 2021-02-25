import encoderLib
import time, os
from micropython import const
from machine import I2C, Pin, Timer, RTC
from machine_i2c_lcd import I2cLcd

LED_PIN = const(2)
DISPLAY_SCL_PIN = const(22)
DISPLAY_SDA_PIN = const(21)
RELAY_PIN = const(10)


class Display:
    DEFAULT_I2C_ADDR = 0x27
    ROWS = 4
    LINES = 20

    def __init__(self):
        i2c = I2C(0, scl=Pin(DISPLAY_SCL_PIN), sda=Pin(DISPLAY_SDA_PIN), freq=400000)
        self.lcd = I2cLcd(i2c, self.DEFAULT_I2C_ADDR, 4, 20)

    def display(self, text):
        lines = text.split('\n')  # type: list
        if len(lines) < 4:
            lines += [''] * (4 - len(lines))
        lines = ['{:<20}'.format(l[:20]) for l in lines]
        self.lcd.putstr('\n'.join([x for x in lines]))

    def print_line(self, line, text, start_pos=0):
        self.lcd.move_to(start_pos, line)
        self.lcd.putstr(text)


LCD = Display()


class RObject:
    def __init__(self):
        self.__events = []

    @property
    def events(self):
        return self.__events

    def emit(self, event, *args):
        self.__events.append([event, args])

    def receive(self, event, *args):
        pass


class EncoderEvents(RObject):
    BTN_PIN = const(27)
    ENC_PIN = [14, 13]

    def __init__(self, on_left, on_right, on_press):
        super(EncoderEvents, self).__init__()
        self._btn = Pin(self.BTN_PIN, Pin.IN, Pin.PULL_UP)
        self._enc = encoderLib.encoder(self.ENC_PIN[0], self.ENC_PIN[1])
        # values
        self.last_enc_value = 0
        self.last_btn_value = 1
        # callbacks
        self.ol_clb = on_left
        self.or_clb = on_right
        self.op_clb = on_press

    def on_left(self):
        print('left')
        self.ol_clb()

    def on_right(self):
        print('right')
        self.or_clb()

    def on_press(self):
        print('press')
        self.op_clb()

    def update(self):
        # encoder
        value = self._enc.getValue()
        if value != self.last_enc_value:
            if value < self.last_enc_value:
                self.on_left()
            else:
                self.on_right()
            self.last_enc_value = value
        # button
        btn_value = int(self._btn.value())
        if self.last_btn_value != btn_value:
            if btn_value == 0:
                self.on_press()
            self.last_btn_value = btn_value


class Controller(RObject):
    title = 'No Title'
    selectable = True
    max_width = 18

    def __init__(self):
        super(Controller, self).__init__()
        self.line = None

    def set_line(self, line):
        self.line = line

    def get_title(self):
        """Left text"""
        return self.title

    def get_value(self):
        """Right Text"""
        return '---'

    def on_enter(self):
        pass

    def on_left(self):
        self.render()

    def on_right(self):
        self.render()

    def on_exit(self):
        pass

    def render(self):
        if self.line is not None:
            text = '{:<{}}'.format(self.get_title(), self.max_width)
            value = self.get_value()
            text = text[:-len(value)] + value
            LCD.print_line(self.line, text, start_pos=1)


class Menu(RObject):
    MODE_SELECT = const(0)
    MODE_EDIT = const(1)

    def __init__(self, items, core):
        super(Menu, self).__init__()
        if not len(items) == 4:
            raise ValueError
        self.items = items
        for i, item in enumerate(self.items):
            item.set_line(i)
        self.core = core
        self.max_index = len(self.items) - 1
        self.current_index = self.items.index([x for x in self.items if x.selectable][0])
        self.mode = self.MODE_SELECT

    def on_left(self):
        if self.mode == self.MODE_SELECT:
            self.current_index -= 1
            if self.current_index < 0:
                self.current_index = self.max_index
            if not self.controller.selectable:
                self.on_left()
            self.update_indicator()
        else:
            self.controller.on_left()

    def on_right(self):
        if self.mode == self.MODE_SELECT:
            self.current_index += 1
            if self.current_index > self.max_index:
                self.current_index = 0
            if not self.controller.selectable:
                self.on_right()
            self.update_indicator()
        else:
            self.controller.on_right()

    @property
    def controller(self):
        return self.items[self.current_index]    # type: Controller

    def on_press(self):
        self.change_focus()
        self.update_indicator()

    def change_focus(self):
        if self.mode == self.MODE_SELECT:
            self.mode = self.MODE_EDIT
            self.clear_left()
            self.controller.on_enter()
        else:
            self.mode = self.MODE_SELECT
            self.clear_right()
            self.controller.on_exit()
        self.update_indicator()

    def render_menu(self):
        for i in self.items:
            i.render()
        self.update_indicator()

    def update_indicator(self):
        if self.mode == self.MODE_SELECT:
            self.clear_left()
            LCD.print_line(self.current_index, '>')
        else:
            self.clear_right()
            LCD.print_line(self.current_index, '<', start_pos=19)

    def clear_left(self):
        for i in range(4):
            LCD.print_line(i, ' ')

    def clear_right(self):
        for i in range(4):
            LCD.print_line(i, ' ', start_pos=Display.LINES-1)

    def apply_events(self):
        objects = self.items[:] + [self.core, self]
        for item in objects:
            e = item.events
            if e:
                while e:
                    ev = e.pop()
                    print('EMIT', ev)
                    for c in objects:
                        c.receive(ev[0], *ev[1])

# =====================================


class ControllerTitle(Controller):
    selectable = False
    title_list = {
        -1: '======',
        0: '=OFF=',
        1: '=ON='
    }

    def __init__(self):
        super(ControllerTitle, self).__init__()
        self.eta = 0
        self.mode = -1

    def get_title(self):
        return self.title_list[self.mode]

    def get_value(self):
        return '00:00:{:02d}'.format(self.eta)

    def on_right(self):
        pass

    def on_left(self):
        pass

    def receive(self, event, *args):
        if event == 'update_eta':
            self.eta = args[0]
            self.render()
        elif event == 'set_mode':
            self.mode = args[0]
            self.render()


class ControllerTime(Controller):
    title = 'Time'
    event_name = ''

    def __init__(self, init_time=0):
        super(ControllerTime, self).__init__()
        self.time = init_time
        self.on_exit()

    def get_value(self):
        h = self.time // 60
        m = self.time - (h * 60)
        return '{}:{}'.format("{:02d}".format(h), "{:02d}".format(m))

    def on_left(self):
        self.time = max(0, self.time-1)

    def on_right(self):
        self.time += 1
        if self.time >= 6000:
            self.time = 0

    def receive(self, event, *args):
        if event == 'reset':
            self.time = 0

    def on_exit(self):
        if self.event_name:
            self.emit(self.event_name, self.time)


    # def on_exit(self):
    #     # TODO: save to flash
    #     pass


class ControllerOnline(ControllerTime):
    title = 'Time ON:'
    event_name = 'online_changed'


class ControllerOffline(ControllerTime):
    title = 'Time OFF:'
    event_name = 'offline_changed'


class ControllerActions(Controller):
    title = 'Action'
    actions = [['Start', 'Stop'], 'Restart', 'Reset', 'Reboot', '<-back']

    def __init__(self):
        super(ControllerActions, self).__init__()
        self.current_index = 0
        self.max_index = len(self.actions) - 1
        self.mode = 0

    def get_value(self):
        return self.current_action()

    def on_left(self):
        self.current_index -= 1
        if self.current_index < 0:
            self.current_index = self.max_index

    def on_right(self):
        self.current_index += 1
        if self.current_index > self.max_index:
            self.current_index = 0

    def current_action(self):
        action = self.actions[self.current_index]
        if isinstance(action, list):
            action = action[self.mode]
        return action

    def on_exit(self):
        action = self.current_action()
        if action != self.actions[-1]:
            self.emit(action.lower().replace(' ', '_'))
        self.current_index = 0

    def receive(self, event, *args):
        if event == 'set_mode':
            self.mode = args[0]


class Program(RObject):
    STATE_ONLINE = 1
    STATE_OFFLINE = 0
    STATE_OFF = -1

    def __init__(self):
        super(Program, self).__init__()
        self.state = self.STATE_ONLINE
        self.led = Pin(LED_PIN, Pin.OUT)
        self.led.value(0)
        self.rtc = RTC()
        self.timer = None
        self.on_time = 0
        self.off_time = 0
        self.eta = 0
        self.emit('set_mode', self.state)

    def start_timer(self):
        # https://micronote.tech/2020/02/Timers-and-Interrupts-with-a-NodeMCU-and-MicroPython/
        # check times
        if self.timer:
            self.stop_timer()
        self.timer = Timer(-2)
        self.timer.init(period=1000, mode=Timer.PERIODIC, callback=self.update_handler)
        self.rest_rtc()

    def rest_rtc(self):
        self.rtc.datetime((2020, 1, 1, 0, 0, 0, 0, 0))

    def stop_timer(self):
        if self.timer:
            self.timer.deinit()
            self.eta = 0
            self.timer = None

    def _get_time_offset(self):
        if not self.timer:
            return 0
        _, _, _, _, h, m, s, _ = self.rtc.datetime()
        return (h * 60 * 60) + (m * 60) + s

    def update_handler(self, *args):
        # get current time offset
        total_sec = self._get_time_offset()
        # compute eta
        # trigger state if need
        if self.state == self.STATE_ONLINE:
            self.eta = self.on_time - total_sec
            if total_sec >= self.on_time:
                self.on_state_triggered(False)
        elif self.state == self.STATE_OFFLINE:
            self.eta = self.off_time - total_sec
            if total_sec >= self.off_time:
                self.on_state_triggered(True)
        self.update_display()

    def update_display(self):
        self.emit('update_eta', self.eta)

    def receive(self, event, *args):
        if event == 'online_changed':
            self.on_time = args[0]
        elif event == 'offline_changed':
            self.off_time = args[0]
        elif event == 'stop':
            if self.state == self.STATE_OFFLINE:
                return
            self.stop_timer()
        elif event == 'start':
            if self.state == self.STATE_ONLINE:
                return
            self.start_timer()
        elif event == 'restart':
            self.stop_timer()
            self.start_timer()
        elif event == 'reset':
            self.stop_timer()

    def on_state_triggered(self, set_online=False):
        print('SWITCH TRIGGERED ->>>')
        self.state = self.STATE_ONLINE if set_online else self.STATE_OFFLINE
        self.rest_rtc()
        self.stop_timer()
        self.start_timer()
        self.led.value(self.state)
        self.emit('set_mode', self.state)


def main():
    items = [
        ControllerTitle(), ControllerOnline(5), ControllerOffline(10), ControllerActions()
    ]
    core = Program()
    menu = Menu(items, core)
    events = EncoderEvents(
        on_left=menu.on_left,
        on_right=menu.on_right,
        on_press=menu.on_press
    )
    menu.render_menu()
    core.start_timer()

    while True:
        try:
            events.update()
            menu.apply_events()
            time.sleep(0.05)
        except KeyboardInterrupt:
            break

main()
