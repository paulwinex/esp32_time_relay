import encoderLib
import time
from micropython import const
from machine import I2C, Pin, Timer, RTC as _RTC, reset
from machine_i2c_lcd import I2cLcd

# constants
LED_PIN = const(23)
LINE_PIN = const(26)
DISPLAY_SCL_PIN = const(22)
DISPLAY_SDA_PIN = const(21)
RELAY_PIN = const(10)
ON = const(1)
OFF = const(0)
# Init real time clock
RTC = _RTC()
RTC.datetime((2020, 1, 1, 0, 0, 0, 0, 0))


class RObject:
    """Base object for event engine"""
    _objects = []

    def __init__(self):
        self.__events = []
        self.__class__._objects.append(self)

    def get_objects(self):
        return self.__class__._objects

    @property
    def events(self):
        return self.__events

    def emit(self, event, *args):
        self.__events.append([event, args])

    def receive(self, event, *args):
        pass


class Display(RObject):
    """LCD Display control"""
    DEFAULT_I2C_ADDR = 0x27
    ROWS = 4
    LINES = 20

    def __init__(self):
        super(Display, self).__init__()
        i2c = I2C(0, scl=Pin(DISPLAY_SCL_PIN), sda=Pin(DISPLAY_SDA_PIN), freq=400000)
        self.lcd = I2cLcd(i2c, self.DEFAULT_I2C_ADDR, 4, 20)
        self.render_enabled = True
        self.timer = None

    def display(self, text):
        if not self.render_enabled:
            return
        lines = text.split('\n')  # type: list
        if len(lines) < 4:
            lines += [''] * (4 - len(lines))
        lines = ['{:<20}'.format(l[:20]) for l in lines]
        self.lcd.putstr('\n'.join([x for x in lines]))

    def print_line(self, line, text, start_pos=0):
        if not self.render_enabled:
            return
        self.lcd.move_to(start_pos, line)
        self.lcd.putstr(text)

    def show_message(self, text, title='ERROR', timeout=3):
        lines = text.split('\n')
        lines = [x.strip()[:20].center(20) for x in lines]
        title = title[:20].center(20)
        self.lcd.clear()
        self.lcd.move_to(0, 0)
        self.lcd.putstr(title)
        for i, line in enumerate(lines[:3], 1):
            self.lcd.move_to(0, i)
            self.lcd.putstr(line)
        if timeout:
            self.render_enabled = False
            self.timer = Timer(2)
            self.timer.init(period=timeout*1000, mode=Timer.ONE_SHOT, callback=self.hide_message)

    def hide_message(self, *args):
        self.timer = None
        self.render_enabled = True
        self.lcd.clear()
        self.emit('rerender')

    def clear(self):
        self.lcd.clear()

    def off(self):
        self.lcd.backlight_off()

    def on(self):
        self.lcd.backlight_on()

    def receive(self, event, *args):
        if event == 'idle_off':
            self.on()
        elif event == 'idle_on':
            self.off()


LCD = Display()


class IdleTimer(RObject):
    """IDLE timer to switch ON/OFF of display"""
    IDLE_TIMEOUT = const(30)

    def __init__(self):
        super(IdleTimer, self).__init__()
        self.idle_timer = Timer(5)
        self.is_idle = False
        self.last_active = time.time()
        self.start_idle_timer()

    def start_idle_timer(self):
        self.idle_timer.init(period=self.IDLE_TIMEOUT * 1000, mode=Timer.PERIODIC, callback=self.on_idle_timeout)
        self.is_idle = False
        self.emit('idle_off')

    def on_idle_timeout(self, *args):
        if self.is_idle:
            return
        current = time.time()
        expire_time = current - self.last_active
        if expire_time > self.IDLE_TIMEOUT:
            self.idle_on()

    def idle_on(self):
        self.emit('idle_on')
        self.is_idle = True

    def idle_off(self):
        self.emit('idle_off')
        self.is_idle = False

    def receive(self, event, *args):
        if event == 'on_key_event':
            # mve or click encoder to exit idle mode
            self.last_active = time.time()
            if self.is_idle:
                self.idle_off()
        if event == 'stop':
            self.idle_timer.deinit()


class Events(RObject):
    """Events listener and executor"""
    BTN_PIN = const(27)
    ENC_PIN = [14, 13]

    def __init__(self, on_left, on_right, on_press):
        super(Events, self).__init__()
        self._btn = Pin(self.BTN_PIN, Pin.IN, Pin.PULL_UP)
        self._enc = encoderLib.encoder(self.ENC_PIN[0], self.ENC_PIN[1])
        # values
        self.last_enc_value = 0
        self.last_btn_value = 1
        # self.objects = [self]
        self._is_idle_mode = False

        # callbacks
        self.ol_clb = on_left
        self.or_clb = on_right
        self.op_clb = on_press

    def on_left(self):
        if not self._is_idle_mode:
            self.ol_clb()
        self.on_any_event()

    def on_right(self):
        if not self._is_idle_mode:
            self.or_clb()
        self.on_any_event()

    def on_press(self):
        if not self._is_idle_mode:
            self.op_clb()
        self.on_any_event()

    def on_any_event(self):
        self.emit('on_key_event')
        self._is_idle_mode = False

    def update(self):
        # encoder
        value = self._enc.getValue()
        if value != self.last_enc_value:
            if value > self.last_enc_value:
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
        # delivery events
        objects = self.get_objects()
        for item in objects:
            e = item.events
            if e:
                while e:
                    ev = e.pop()
                    for c in objects:
                        c.receive(ev[0], *ev[1])

    def receive(self, event, *args):
        if event == 'idle_on':
            self._is_idle_mode = True


class Program(RObject):
    """Relay logic"""
    STATE_STOPPED = 0
    STATE_OFFLINE = 1
    STATE_ONLINE = 2

    def __init__(self):
        super(Program, self).__init__()
        self.state = 0
        self.led = Pin(LED_PIN, Pin.OUT)
        self.power = Pin(LINE_PIN, Pin.OUT)
        self.led.value(0)
        self.timer = None
        self.on_time = 0
        self.off_time = 0
        self.eta = 0
        self.last_checked_time = 0
        self.set_state(self.STATE_STOPPED)

    def start_timer(self):
        # https://micronote.tech/2020/02/Timers-and-Interrupts-with-a-NodeMCU-and-MicroPython/
        if self.on_time == 0:
            LCD.show_message('ON time is ZERO')
            return
        if self.off_time == 0:
            LCD.show_message('OFF time is ZERO')
            return
        if self.state != self.STATE_STOPPED:
            return
        if self.timer:
            self.stop_timer()
        self.timer = Timer(-2)
        self.timer.init(period=1000, mode=Timer.PERIODIC, callback=self.update_handler)
        self.rest_rtc()
        return True

    def stop_timer(self, set_state=False):
        if self.state == self.STATE_STOPPED:
            return
        if self.timer:
            self.timer.deinit()
            self.timer = None
        if set_state:
            self.set_state(self.STATE_STOPPED)
        return True

    def set_state(self, state):
        self.state = state
        self.emit('set_state', self.state)

    def rest_rtc(self):
        self.last_checked_time = time.time()
        self.eta = 0

    def update_handler(self, *args):
        # get current time offset
        offs = time.time() - self.last_checked_time
        if self.state == self.STATE_ONLINE:
            # compute eta
            self.eta = self.on_time - offs
            if offs >= self.on_time:
                self.on_state_triggered(self.STATE_OFFLINE)
        elif self.state == self.STATE_OFFLINE:
            # compute eta
            self.eta = self.off_time - offs
            if offs >= self.off_time:
                self.on_state_triggered(self.STATE_ONLINE)
        self.update_display()

    def update_display(self):
        self.emit('update_eta', self.eta)

    def receive(self, event, *args):
        if event == 'online_changed':
            self.on_time = args[0]
        elif event == 'offline_changed':
            self.off_time = args[0]
        elif event == 'stop':
            self.stop_timer()
            self.set_state(self.STATE_STOPPED)
            self.set_power(OFF)
            self.eta = 0
        elif event == 'start':
            if self.start_timer():
                self.set_state(self.STATE_ONLINE)
                self.set_power(ON)
        elif event == 'restart':
            self.emit('stop')
            self.emit('start')
        elif event == 'reset':
            self.stop_timer()
            self.set_state(self.STATE_STOPPED)
            self.set_power(OFF)
        elif event == 'reboot':
            reset()

    def on_state_triggered(self, state=0):
        self.rest_rtc()
        self.set_state(state)
        self.set_power(max(0, state - 1))

    def set_power(self, value=False):
        v = int(bool(value))
        self.led.value(v)
        self.power.value(v)


class Controller(RObject):
    """Base controller class (GUI line)"""
    title = 'No Title'
    selectable = True
    max_width = 18

    def __repr__(self):
        return '<Ctrl {}>'.format(self.title)

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
        self.render()

    def render(self):
        if self.line is not None:
            text = '{:<{}}'.format(self.get_title(), self.max_width)
            value = self.get_value()
            if value:
                text = text[:-len(value)] + value
            LCD.print_line(self.line, text, start_pos=1)


class Menu(RObject):
    """Menu GUI control"""
    MODE_SELECT = const(0)
    MODE_EDIT = const(1)

    def __init__(self, items):
        super(Menu, self).__init__()
        if not len(items) == 4:
            raise ValueError
        self.items = items
        for i, item in enumerate(self.items):
            item.set_line(i)
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

    def receive(self, event, *args):
        if event == 'rerender':
            self.render_menu()


class ControllerTitle(Controller):
    """First line controller"""
    selectable = False
    title_list = {
        Program.STATE_STOPPED: 'OFFLINE'.center(18).replace(' ', '='),
        Program.STATE_ONLINE:  '==ON===',
        Program.STATE_OFFLINE: '==OFF==',
    }

    def __init__(self):
        super(ControllerTitle, self).__init__()
        self.eta = 0
        self.mode = Program.STATE_STOPPED

    def get_title(self):
        return self.title_list[self.mode]

    def get_value(self):
        if self.mode == Program.STATE_STOPPED:
            return ''
        m, s = divmod(self.eta, 60)
        h, m = divmod(m, 60)
        return '{:02d}:{:02d}:{:02d}'.format(h, m, s)

    def receive(self, event, *args):
        if event == 'update_eta':
            self.eta = args[0]
            self.render()
        elif event == 'set_state':
            self.mode = args[0]
            self.render()


class ControllerTime(Controller):
    """Base time controller"""
    title = 'TIME'
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
        self.time += 1
        if self.time >= 6000:
            self.time = 0
        super(ControllerTime, self).on_right()

    def on_right(self):
        self.time = max(0, self.time-1)
        super(ControllerTime, self).on_left()

    def receive(self, event, *args):
        if event == 'reset':
            self.time = 0
            self.emit(self.event_name, self.time)
            self.render()

    def on_exit(self):
        if self.event_name:
            self.emit(self.event_name, self.time*60)

    # def on_exit(self):
    #     # TODO: save to flash
    #     pass


class ControllerOnline(ControllerTime):
    """Online time controller"""
    title = 'ON'
    event_name = 'online_changed'


class ControllerOffline(ControllerTime):
    """Offline time controller"""
    title = 'OFF'
    event_name = 'offline_changed'


class ControllerActions(Controller):
    """Commands controller"""
    title = 'ACTION'
    MODE_ACTIVE = 1
    MODE_INACTIVE = 0
    null_action = '<='
    actions_base = ['RESET', 'REBOOT', null_action]
    actions = {
        0: ['START']+actions_base,
        1: ['STOP']+actions_base,
    }

    def __init__(self):
        super(ControllerActions, self).__init__()
        self.current_index = 0
        self.max_index = 0
        self.mode = self.MODE_INACTIVE

    def set_mode(self, value):
        self.mode = value
        self.max_index = len(self.actions[value]) - 1
        self.render()

    def get_title(self):
        return super(ControllerActions, self).get_title()

    def get_value(self):
        return self.current_action()

    def on_left(self):
        self.current_index -= 1
        if self.current_index < 0:
            self.current_index = self.max_index
        super(ControllerActions, self).on_left()

    def on_right(self):
        self.current_index += 1
        if self.current_index > self.max_index:
            self.current_index = 0
        super(ControllerActions, self).on_right()

    def current_action(self):
        return self.actions[self.mode][self.current_index]

    def on_exit(self):
        action = self.current_action()
        if action != self.null_action:
            event = action.lower().replace(' ', '_')
            self.emit(event)
        self.current_index = 0
        super(ControllerActions, self).on_exit()

    def receive(self, event, *args):
        if event == 'set_state':
            if args[0] == Program.STATE_STOPPED:
                self.set_mode(self.MODE_INACTIVE)
            else:
                self.set_mode(self.MODE_ACTIVE)
            self.render()


def main():
    core = Program()
    items = [
        ControllerTitle(), ControllerOnline(5), ControllerOffline(5), ControllerActions()
    ]
    menu = Menu(items)
    idle = IdleTimer()
    events = Events(
        on_left=menu.on_left,
        on_right=menu.on_right,
        on_press=menu.on_press
    )
    menu.render_menu()

    # Main loop
    while True:
        try:
            events.update()
            time.sleep(0.05)
        except KeyboardInterrupt:
            events.emit('stop')
            events.update()
            break
