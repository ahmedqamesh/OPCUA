from opcua import Client
import time
url ="opc.tcp://localhost:4840/"
client=Client(url)
client.connect()
print("Client connected")

while True:
    get_ADCTRIM = client.get_node("ns=2;i=8476")
    ADCTRIM = get_ADCTRIM.get_value()
    print("ADCTRIM:",ADCTRIM)
    
    get_NodeID = client.get_node("ns=2;i=8530")
    NodeID =get_NodeID.get_value()
    print("NodeID:",NodeID)
    
    get_Status = client.get_node("ns=2;i=10395")
    Status = get_Status.get_value()
    print ("Status:",Status)
    time.sleep(1)