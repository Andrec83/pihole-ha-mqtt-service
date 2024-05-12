#!/usr/bin/python
import subprocess, sys
import paho.mqtt.client as mqtt
import time
import os
import json


topic_status_base = 'pihole/groups/state/'
topic_set_base = 'pihole/groups/set/'
group_name_filter = 'block'
env_path = '/etc/environment'


""" mqtt function on connect """
def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    # send the config messages
    for msg in config_messages:
        client.publish(msg['topic'], payload=msg['payload'], qos=0, retain=False)
    send_group_status()

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe([("pihole/groups/#", 1)])


""" mqtt function on message received """
def on_message(client, userdata, message):
    topic = message.topic
    payload = message.payload.decode()
    print(f"Message received: {topic}: {payload}")
    if topic_status_base in topic:
        with open('/home/pi/mqtt_update.txt', 'a+') as f:
            f.write("received base request")
    elif topic_set_base in topic:
        group = topic.replace(topic_set_base,'')
        if payload in ["0", "1"]:
            update = update_group_state(group, payload)
            if update == 0:
                send_group_status(group)

        else:
            print(f"Received unexpected payload {payload} for topic {topic}")


""" function to update the group status """
def update_group_state(group, state):
    command = f'sqlite3 /etc/pihole/gravity.db "update \'group\' set \'enabled\'={state} where name=\'{group}\'";'
    result = execute_command(command)
    print(f"command: {command} -  result {result}")
    for line in result:
        # print(line)
        if "error" in line.lower():
            print("error writing in DB, do you have the right access?")
            return 1
    command = "/usr/local/bin/pihole restartdns reload-lists >/dev/null"
    result = execute_command(command)
    return 0


""" mqtt function to send status update """
def send_group_status(selected_group=None):
    group_list = get_group_status(group_name_filter)
    for group in group_list:
        if selected_group is None or selected_group == group:
            topic = f"pihole/groups/state/{group}"
            payload = group_list[group]
            client.publish(topic, payload=payload, qos=0, retain=False)


""" function to make command calls """
def execute_command(command):
    try:
        result = subprocess.check_output(command, shell = True, executable = "/bin/bash", stderr = subprocess.STDOUT)

    except subprocess.CalledProcessError as cpe:
        result = cpe.output

    finally:
        if result is not None:
            output = [line.decode() for line in result.splitlines()]
        else:
            output = []
    return output


""" collect all the groups that contains the workd 'Block' in their name """
def get_group_status(group_name_filter=''):
    command = f'sqlite3 /etc/pihole/gravity.db "select * from \'group\' where lower(name) like \'%{group_name_filter}%\'";'
    group_list = {}

    for line in execute_command(command):
        item = line.split('|')
        if type(item)==list and len(item)>2:
            status = item[1]
            group = item[2]
            if group_name_filter == '' or group_name_filter.lower() in group.lower():
                group_list[group] = status
    return group_list

group_list = get_group_status(group_name_filter)

# print(group_list)


""" collect system information to attach to the config messages TODO: Add error handling"""
system = {}
system['debian_version'] = execute_command('cat /etc/debian_version')[0]
system['interface'] = execute_command("route | grep default | awk '{print $NF}'")[0]
system['mac_address'] = execute_command(f"ifconfig | grep {system['interface']} -A 7 | grep ether | awk '{{print $2}}'")[0]
system['mac_address_no_columns'] = system['mac_address'].replace(':','')
# print(system)


""" prepare the config messages """
config_messages = []
debian_version = system['debian_version']
interface = system['interface']
mac_address = system['mac_address']
mac_address_no_columns = system['mac_address_no_columns']
for group_name in group_list:
    if 'block' in group_name.lower():
        payload = {"name": f"PiHole Group {group_name}",
                   "unique_id": f"pihole_group_{group_name}",
                   "device": {
                       "identifiers": f"PiHole_{mac_address_no_columns}",
                       "connections": [["mac", mac_address]],
                       "manufacturer": "Raspberry",
                       "model": "Pi Zero W",
                       "name": "Raspberry Pi Zero W",
                       "sw_version": f"Debian {debian_version}"},
                   "icon": "mdi:light-switch",
                   "state_topic": f"{topic_status_base}{group_name}",
                   "command_topic": f"{topic_set_base}{group_name}",
                   "payload_on": 1,
                   "payload_off": 0,
                   "state_on": 1,
                   "state_off": 0,
                   "optimistic": False
                  }
        config_messages.append({'topic': f'homeassistant/switch/PiHole_groups/{group_name}/config', 'payload': json.dumps(payload)})
# print(config_messages)


""" connect to the MQTT server """
user = os.environ.get('MQTT_USER')
pasw = os.environ.get('MQTT_PASSWORD')
addr = os.environ.get('MQTT_SERVER')
port = os.environ.get('MQTT_PORT')
port = int(port) if port is not None else None

if addr is None:
    envdict = {}
    with open(env_path) as env_var:
        file = env_var.read()
        for line in file.splitlines():
            envdict[line.split('=')[0]] = line.split('=')[1]
    user = envdict['MQTT_USER'].replace('"','').replace("'","")
    pasw = envdict['MQTT_PASSWORD'].replace('"','').replace("'","")
    addr = envdict['MQTT_SERVER'].replace('"','').replace("'","")
    port = envdict['MQTT_PORT'].replace('"','').replace("'","")

port = int(port) if port is not None else None
# print(user, pasw, addr, port)

client = mqtt.Client()  # create new instance
client.username_pw_set(user, password=pasw)    #set username and password
client.on_connect = on_connect  # attach function to callback
client.on_message = on_message  # attach function to callback

client.connect(addr, port=port)  # connect to broker

client.loop_forever()
