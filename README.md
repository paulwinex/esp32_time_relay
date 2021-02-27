# Time Relay Controller

Simple time relay based on ESP32 + MicroPython

## Features

- Single channel for any relay

- Set ON and OFF timer with infinite loop between them.

- Idle mode with turn off display after 30 sec after last activity and turn on on encoder moved.

- Additional commands: RESET, REBOOT

- LED indicator which show current state.

## Code features

- Simple implementation of event-listener system

- All logic based on classes

Hardware:

- ESP-WROOM-32

- Relay 200v

- LCD Display 2004a 20x4 https://www.beta-estore.com/download/rk/RK-10290_410.pdf

- Encoder

- LED

## Scheme

... IMAGE TODO...

## Used external libs

- encoderLib.py

    Encoder library for MicroPython

- python_lcd

    LCD control library. Used only files: lcd_api.py and machine_i2c_lcd.py


# How to install

1. Connect on the breadboard or weld hardware as on scheme

2. Flash MicroPython to ESP32

3. Upload external library to ESP32 (you can get it from libs dir) to root of file system

4. Upload main.py and time_relay.py to ESP32

5. Reboot
