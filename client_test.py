from opcua import Client
import time

# define the OPCUA address
url ="opc.tcp://localhost:4840/"
client=Client(url)
client.connect()
print('The OPCUA Client connected')    

while True:
    get_ADCTRIM = client.get_node("ns=2;i=8476")
    ADCTRIM = get_ADCTRIM.get_value()
    
    get_NodeID = client.get_node("ns=2;i=8530")
    NodeID =get_NodeID.get_value()
    
    get_Status = client.get_node("ns=2;i=10395")
    Status = get_Status.get_value()
    
    
    Info = "Time: %s | Status: %s | NodeID: %i |  ADCTRIM: %i" %(time.ctime(), Status, NodeID, ADCTRIM)
    print(Info)
    
    time.sleep(2)