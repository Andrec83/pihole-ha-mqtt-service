# pihole-ha-mqtt-service
Pihole service that exposes group management (enable/disable) to Home Assistant with autoconfiguration

To install on Raspberry PI:
1) download the file mqtt-service.py on you Raspberry PI. I put mine on the root home directory:
   ```
   cd /root/ && sudo wget https://github.com/Andrec83/pihole-ha-mqtt-service/blob/main/mqtt-service.py
   ```
3) add to the file /etc/environment the following variables:
   ```
   MQTT_USER="<the user that is authorised to interact with the MQTT server>"
   MQTT_PASSWORD="<the password that authenticates the user on the MQTT server>"
   MQTT_SERVER="<server IP address, in the form of 192.168.X.X>"
   MQTT_PORT=<the port of the MQTT server>
   ```
4) amend the script mqtt-service.py, at the top of the script you should change the variables to your liking:
   ```
   topic_status_base = 'pihole/groups/state/'
   topic_set_base = 'pihole/groups/set/'
   group_name_filter = 'block'  # > I named all the groups that I want to manage via Home Assistant "block-xxx" or "xxx-block-xxx", therefore filtering the group by the word "block" limit the entries in HA to only what I need to control
   ```
5) download the file requirements.txt and install the dependencies:
   ```
   wget https://github.com/Andrec83/pihole-ha-mqtt-service/blob/main/requirements.txt && sudo pip3 install -r requirements.txt
   ```
6) test the script:
   ```
   sudo python3 mqtt-service.py
   ```
   you should see in your Home Assistant the new groups with the ability to enable or disable them
7) if the test above worked well, install the script as a service (taken from https://medium.com/codex/setup-a-python-script-as-a-service-through-systemctl-systemd-f0cc55a42267):
   ```
   sudo nano /etc/systemd/system/mqtt-ha.service
   ```
   ```
    [Unit]
    Description=Update groups from HA via MQTT service
    After=multi-user.target
    [Service]
    Type=simple
    Restart=always
    ExecStart=/usr/bin/python3 /root/mqtt-service.py
    [Install]
    WantedBy=multi-user.target
   ```
8) enable and start the service:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable mqtt-ha.service
   sudo systemctl start mqtt-ha.service
   ```
10) check that everything is working well:
    ```
    sudo systemctl status mqtt-ha.service
    ```


The script can certainly be improved and generalised, happy for any contribution to come along. I still have to add a way to report that a group had been enabled/disabled from the PiHole front-end. 
I'll add - when I need it next - reporting on the general metrics (number of queries, etc) and maybe something more. 

Credit to https://community.home-assistant.io/t/pihole-5-enable-disable-groups-block-internet/268927 for the insipration on how to manage PiHole via bash, 
and https://medium.com/codex/setup-a-python-script-as-a-service-through-systemctl-systemd-f0cc55a42267 for the service management aspect. 
   
   

