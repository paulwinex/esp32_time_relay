import time_relay
import time


time_relay.LCD.show_message('Time Relay\n----------', title='', timeout=0)
time.sleep(2)
time_relay.LCD.clear()
time_relay.main()
