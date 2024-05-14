#!/usr/bin/python
import subprocess
import sys
import paho.mqtt.client as mqtt
import time
import os
import json
import re


""" configuration TODO move them to a separate files and prepare install script """
topic_group_status_base = 'pihole/groups/state/'  # topic used to publish the status of the groups
topic_group_set_base = 'pihole/groups/set/'  # topic used to receive commands from HomeAssistant
topic_global_status_base = 'pihole/state/' # topic used to publish the status of pihole filtering
topic_global_set_base = 'pihole/set'  # topic used to receive the enable/disable command from HA
group_name_filter = 'block'  # keyword used to filter the PiHole group names that we want to expose
topic_stat_base = 'pihole/stats/state/'  # topic used to publish the status of the statistics
env_path = '/etc/environment'  # path to the environment file with login credentials and address
send_update_frequency = 5  # send an update every X seconds

""" stores the known groups, stats and their status, for the regular updates """
stored_groups = {}
stored_stats = {}
config_messages = []


def on_connect(mqtt_client, userdata, flags, rc):
    """
    mqtt function on connect: publishes the configuration messages to HomeAssistant
    and subscribes to the topic defined at the top of the screen

    """
    print("Connected with result code " + str(rc))
    # send the config messages
    for msg in config_messages:
        mqtt_client.publish(msg['topic'], payload=msg['payload'], qos=0, retain=False)
    send_group_status()
    send_blocking_status()

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    mqtt_client.subscribe([(f"pihole/#", 1)])


def on_message(mqtt_client, userdata, message):
    """
    mqtt function on message received: request update for the group,
    received as part of the topic {topic_group_set_base}{group_name}
    """
    topic = message.topic
    payload = message.payload.decode()
    # print(f"Message received: {topic}: {payload}")
    if topic_group_set_base in topic:
        print(f"Message received: {topic}: {payload}")
        group = topic.replace(topic_group_set_base, '')
        if payload in ["0", "1"]:
            update = update_group_state(group, payload)
            if update == 0:
                send_group_status(group)
        else:
            print(f"Received unexpected payload {payload} for topic {topic}")
    elif topic_global_set_base in topic:
        print(f"Message received: {topic}: {payload}")
        if payload in ["0", "1"]:
            update = update_blocking_state(payload)
            send_blocking_status(update)
        else:
            print(f"Received unexpected payload {payload} for topic {topic}")


def update_blocking_state(st):
    """ function to update the blocking enable/disabled status on PiHole """
    state = ['disable', 'enable'][int(st)]
    pihole_command = f"/usr/local/bin/pihole {state}"
    pihole_output = execute_command(pihole_command)
    return pihole_output


def send_blocking_status(status_string=None):
    """
    function to update the current status of pihole
    return immediately the status of pihole and update the sensor if available
    """
    # update the switch status
    if status_string is None:
        pihole_command = f"/usr/local/bin/pihole status"
        pihole_output = execute_command(pihole_command)
    else:
        pihole_output = status_string
    state_topic = f"{topic_global_status_base}blocking"
    if 'enabled' in ''.join(pihole_output).lower():
        status_payload = 1  # pihole is enabled
    elif 'disabled' in ''.join(pihole_output).lower():
        status_payload = 0  # pihole is disabled
    else:
        print("unable to retrieve the status of PiHole with command 'pihole status'")
        return -1
    client.publish(state_topic, payload=status_payload, qos=0, retain=False)
    # update the sensor status if available
    status_sensor_payload = ['Offline', 'Active'][status_payload]
    status_sensor_topic = f"{topic_stat_base}PiHole_Status"
    client.publish(status_sensor_topic, payload=status_sensor_payload, qos=0, retain=False)
    stored_stats['PiHole_Status'] = status_sensor_payload
    return 0


def update_group_state(grp, st):
    """ function to update the group enable/disabled satus on PiHole """
    pihole_command = f'sqlite3 /etc/pihole/gravity.db "update \'group\' set \'enabled\'={st} where name=\'{grp}\'";'
    pihole_result = execute_command(pihole_command)
    print(f"command: {pihole_command} - result {pihole_result}")
    for line in pihole_result:
        if "error" in line.lower():
            print("error writing in DB, do you have the right access?")
            return 1
    pihole_command = "/usr/local/bin/pihole restartdns reload-lists >/dev/null"
    execute_command(pihole_command)
    return 0


def send_group_status(selected_group=None):
    """
    mqtt function to send status update,
    send all if selected_group is not passed to the function,
    or only the selected_group if passed
    input: selected_group: group name as String
    """
    groups_list = get_group_status(group_name_filter)
    for group in groups_list:
        if selected_group is None or selected_group == group:
            topic = f"{topic_group_status_base}{group}"
            payload = groups_list[group]
            client.publish(topic, payload=payload, qos=0, retain=False)
            # store the current value
            stored_groups[group] = payload


def send_stat_status(stat_dict):
    """
    mqtt function to send status update of the stat.
    input: stat_dict as Dict
    """
    topic = f"{topic_stat_base}{stat_dict['id']}"
    payload = stat_dict['value']
    client.publish(topic, payload=payload, qos=0, retain=False)
    # store the current value
    stored_stats[stat_dict['id']] = payload


def execute_command(command_string):
    """
    function to make shell command calls
    if the command is successful, return the message
    if it is unsuccessful, returns the error for logging
    """
    command_result = None
    try:
        command_result = subprocess.check_output(command_string,
                                                 shell=True,
                                                 executable="/bin/bash",
                                                 stderr=subprocess.STDOUT)

    except subprocess.CalledProcessError as cpe:
        command_result = cpe.output

    finally:
        if command_result is not None:
            output = [line.decode() for line in command_result.splitlines()]
        else:
            output = []
    return output


def get_group_status(name_filter=''):
    """
    collects all the groups filtering by group_name for the word {name_filter},
    passed as variable and defined at the top of the script as {group_name_filter}
    the select statement return a list of groups with columns separated by "|", eg:

    id|enabled|name|date_added|date_modified|description
    0|1|Default|1623254719|1647475595|Base Group

    """
    command_string = f'sqlite3 /etc/pihole/gravity.db "select * from \'group\' where lower(name) like \'%{group_name_filter}%\'";'
    group_dict = {}

    for line in execute_command(command_string):
        item_list = line.split('|')
        if type(item_list) == list and len(item_list) > 2:
            status = item_list[1]  # enabled
            group = item_list[2]  # name
            if name_filter == '' or name_filter.lower() in group.lower():
                group_dict[group] = status
    return group_dict


def clean_string(s):
    """
    strips a string from non-printable characters
    it can be probably removed as overkill
    """
    return re.sub(r'[^ -~]+', '', s).strip()


def prepare_pihole_config_message():
    """ 
    create the config message dict for HomeAssistant switch autoconfiguration 
    to enable and disable entirely the DNS filtering
    """
    payload = {"name": f"PiHole Global Blocking",
               "unique_id": f"pihole_global_{mac_address_no_columns}",
               "device": {
                   "identifiers": f"PiHole_{mac_address_no_columns}",
                   "connections": [["mac", mac_address]],
                   "manufacturer": "Raspberry",
                   "model": "Pi Zero W",
                   "name": "Raspberry Pi Zero W",
                   "sw_version": f"Debian {debian_version}"},
               "icon": "mdi:lock",
               "state_topic": f"{topic_global_status_base}blocking",
               "command_topic": f"{topic_global_set_base}blocking",
               "payload_on": 1,
               "payload_off": 0,
               "state_on": 1,
               "state_off": 0,
               "optimistic": False
               }
    return payload


def prepare_groups_config_message(group_name_string):
    """ create the config message dict for HomeAssistant switches autoconfiguration """
    payload = {"name": f"PiHole Group {group_name_string}",
               "unique_id": f"pihole_group_{group_name_string}",
               "device": {
                   "identifiers": f"PiHole_{mac_address_no_columns}",
                   "connections": [["mac", mac_address]],
                   "manufacturer": "Raspberry",
                   "model": "Pi Zero W",
                   "name": "Raspberry Pi Zero W",
                   "sw_version": f"Debian {debian_version}"},
               "icon": "mdi:lock",
               "state_topic": f"{topic_group_status_base}{group_name_string}",
               "command_topic": f"{topic_group_set_base}{group_name_string}",
               "payload_on": 1,
               "payload_off": 0,
               "state_on": 1,
               "state_off": 0,
               "optimistic": False
               }
    return payload


def prepare_stats_config_message(stat_dict):
    """ create the config message dict for HomeAssistant stats autoconfiguration """
    payload = {"name": f"PiHole {stat_dict['name']}",
               "uniq_id": f"pihole_stat_{stat_dict['id']}",
               "device": {
                   "identifiers": f"PiHole_{mac_address_no_columns}",
                   "connections": [["mac", mac_address]],
                   "manufacturer": "Raspberry",
                   "model": "Pi Zero W",
                   "name": "Raspberry Pi Zero W",
                   "sw_version": f"Debian {debian_version}"},
               "icon": "mdi:chart-areaspline",
               "~": topic_stat_base,
               "stat_t": f"~{stat_dict['id']}",
               "val_tpl": "{{value}}"
               }
    if 'unit' in stat:
        payload["unit_of_meas"] = stat['unit']
    stored_stats[stat['id']] = None
    return payload


def convert_type(value_string):
    """
    converts the value_string to the appropriate type
    :param value_string: String
    :return: converted_value:
      - int if value_string is a representation of an int
      - float if value_string is a representation of a float
      - string if value_string is a string
    """
    if value_string.replace('.', '', 1).isnumeric() and value_string.isnumeric():  # we got an int
        converted_value = int(value_string)
    elif value_string.replace('.', '', 1).isnumeric() and not value_string.isnumeric():  # we got a float
        converted_value = float(value_string)
    else:
        converted_value = value_string
    return converted_value


def parse_stats(stat_string):
    """
    parses the stats from the command "pihole -c -e" passed as a string
    :param stat_string: String
    :return: stats_list: List of stats dictionaries
    """
    regexes = {'Hostname': '(?:Hostname:)[ ]+(\w+)',
               'Uptime': '(?:Uptime:)[ ]+([\d]+ [\w,:]+ [\d:]+)',
               'Task Load 1min': '(?:Task Load:)[ ]+([\d\.]+)',
               'Task Load 5min': '(?:Task Load:)[ ]+[\d\.]+[ ]+([\d\.]+)',
               'Task Load 15min': '(?:Task Load:)[ ]+[\d\.]+[ ]+[\d\.]+[ ]+([\d\.]+)',
               'Pihole Active Tasks': '(?:Active:)[ ]+([\d]+)',
               'Pihole Total Tasks': '(?:Active:)[ ]+[\d]+ of ([\d]+)[ ]\w+',
               'CPU Usage': '(?:CPU usage:)[ ]+([\d]+)(%)',
               'CPU Freq': '(?:CPU usage:[ ]+[\d]+%)[ ]+\((\d+)[ ](\w+)',
               'CPU Temp': '(?:CPU usage:[ ]+[\d]+%)[ ]+\(\d+[ ]\w+[ @]+(\d+)(\w)',
               'RAM Usage': '(?:RAM usage:)[ ]+([\d]+)(%)',
               'RAM Used': '(?:RAM usage:[ ]+[\d]+\%)[ ]+\(Used: (\d+)[ ]+(\w+)',
               'RAM Total': '(?:RAM usage:[ ]+[\d]+\%)[ ]+\(Used: \d+[ ]+\w+[ ]+of[ ]+(\d+)[ ]+(\w+)',
               'HDD Usage': '(?:HDD usage:)[ ]+([\d]+)(%)',
               'HDD Used': '(?:HDD usage:[ ]+[\d]+\%)[ ]+\(Used: (\d+)[ ]+(\w+)',
               'HDD Total': '(?:HDD usage:[ ]+[\d]+\%)[ ]+\(Used: \d+[ ]+\w+[ ]+of[ ]+(\d+)[ ]+(\w+)',
               'PiHole Status': '(?:Pi-hole: )(\w+)',
               'Site blocked': '(?:Blocking: )(\w+)',
               'Request Blocked pct': '(?:Blocked: )(\w+)',
               'Requests Blocked Total': '(?:Total: )(\w+)',
               'Requests Total': '(?:Total: )\w+[ ]+of[ ]+(\d+)'
               }

    stats_list = []
    for parser in regexes:
        try:
            stat_id = parser.strip().replace(' ', '_')
            value = re.findall(regexes[parser], stat_string)[0]
            if type(value) == tuple:
                value, unit = value
                value = convert_type(value)
                stats_list.append({"name": parser, 'id': stat_id, 'value': value, 'unit': unit})
            else:
                value = clean_string(value.strip())
                value = convert_type(value)
                stats_list.append({"name": parser, 'id': stat_id, 'value': value})
        except Exception as e:
            print('unable to parse: ', parser, ' error ', e)

    return stats_list


def update_stat_pihole():
    stat_command = "pihole -c -e"
    stat_result = execute_command(stat_command)
    stats_list = parse_stats(' '.join(stat_result))
    for st in stats_list:
        # of the stats was not picket-up for any reason before, send the config message and status
        if st['id'] not in stored_stats:
            stat_pl = prepare_stats_config_message(st)
            conf_message = {'topic': f'homeassistant/sensor/PiHole_stats/{st["id"]}/config',
                            'payload': json.dumps(stat_pl)}
            config_messages.append(conf_message)
            client.publish(conf_message['topic'], payload=conf_message['payload'], qos=0, retain=False)
            send_stat_status(st)
        # else check if the stat change, and update it if so
        elif stored_stats[st['id']] is None or st['value'] != stored_stats[st['id']]:
            send_stat_status(st)


""" collects the list of groups available on PiHole """
group_list = get_group_status(group_name_filter)

""" collect system information to attach to the config messages TODO: Add error handling """
debian_version = execute_command('cat /etc/debian_version')[0]
interface = execute_command("route | grep default | awk '{print $NF}'")[0]
mac_address = execute_command(f"ifconfig | grep {interface} -A 7 | grep ether | awk '{{print $2}}'")[0]
mac_address_no_columns = mac_address.replace(':', '')

""" capture the stats from pihole """
command = "pihole -c -e"
result = execute_command(command)
stats = parse_stats(' '.join(result))

""" create the config messages for home assistant """
for group_name in group_list:
    if group_name_filter in group_name.lower():
        group_payload = prepare_groups_config_message(group_name)
        config_messages.append({'topic': f'homeassistant/switch/PiHole_groups/{group_name}/config',
                                'payload': json.dumps(group_payload)})
for stat in stats:
    stat_payload = prepare_stats_config_message(stat)
    config_messages.append({'topic': f'homeassistant/sensor/PiHole_stats/{stat["id"]}/config',
                            'payload': json.dumps(stat_payload)})

""" add an entity to enable/disable the entire pihole filtering """
pihole_payload = prepare_pihole_config_message()
config_messages.append({'topic': f'homeassistant/switch/PiHole/blocking/config',
                        'payload': json.dumps(pihole_payload)})

""" load the connection credentials, address and port from environment file """
user = os.environ.get('MQTT_USER')
pasw = os.environ.get('MQTT_PASSWORD')
addr = os.environ.get('MQTT_SERVER')
port = os.environ.get('MQTT_PORT')
port = int(port) if port is not None else None

""" when running as s service, read directly from the file instead """
if addr is None:
    envdict = {}
    with open(env_path) as env_var:
        file = env_var.read()
        for item in file.splitlines():
            envdict[item.split('=')[0]] = item.split('=')[1]
    user = envdict['MQTT_USER'].replace('"', '').replace("'", "")
    pasw = envdict['MQTT_PASSWORD'].replace('"', '').replace("'", "")
    addr = envdict['MQTT_SERVER'].replace('"', '').replace("'", "")
    port = envdict['MQTT_PORT'].replace('"', '').replace("'", "")

""" convert the port number as int """
port = int(port) if port is not None else None

""" connect to the MQTT server """
client = mqtt.Client()  # create new instance
client.username_pw_set(user, password=pasw)    # set username and password
client.on_connect = on_connect  # attach function to callback
client.on_message = on_message  # attach function to callback
client.connect(addr, port=port)  # connect to broker

""" starts a separate process to listen to messages from HomeAssistant """
client.loop_start()

""" send updates when necessary """
while True:
    # update group status or add groups when they are modified by the PiHole frontend or some other tool
    group_list = get_group_status(group_name_filter)
    for group_name in group_list:
        if group_name_filter in group_name.lower():
            if group_name not in stored_groups:
                # we need to add the new group
                group_payload = prepare_groups_config_message(group_name)
                client.publish(f'homeassistant/switch/PiHole_groups/{group_name}/config',
                               payload=json.dumps(group_payload), qos=0, retain=False)
                send_group_status(group_name)
            elif group_list[group_name] != stored_groups[group_name]:
                # we need to update the status
                send_group_status(group_name)

    # update stats from PiHole
    update_stat_pihole()
    time.sleep(send_update_frequency)
