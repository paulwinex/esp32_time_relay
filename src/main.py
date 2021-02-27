import time_rele
import time


time_rele.LCD.show_message('Time Relay\n----------', title='', timeout=0)
time.sleep(2)
time_rele.LCD.clear()
time_rele.main()
