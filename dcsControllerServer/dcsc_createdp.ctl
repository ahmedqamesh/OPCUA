/**
Create data points matching OPCUA address space and configure periphery address configs.

Steps:
  * Initialize variables
  * Create data point types for PSPP, SCB and DCS Controller
  * Create master data points for these types for lateron mass parametrization
  * Search internal data point of OPCUA server and check if it is running. Note that the data point
    must be named 'dist_1:_DCSControllerServer'.
  * Search for OPCUA data subscription that is named 'OPCUADATASUB'. If the corresponding data point
    does not exist, but it only exists one subscription, then that is taken.
  * Remove existing DCS Controller data points for a clean makeover because nodes on the CAN bus may
    have changed.
  * Get separator (currently there is no use for it in this script).
  * Put together arbitrary request id.
  * Use functionality of internal data points to list all available DCS Controller on the server.
  * Loop over these names, create data points and address attributes.

Author: Sebastian Scholz
Contact: sebastian.scholz@cern.ch
    
(c) 2018
*/

main()
{
  DebugTN("Welcome to DCS Controller integration script for WinCC OA!");

  // Initialization
  string dcsc = "DCSController";
  dyn_dyn_string dptNamesPSPP, dptNamesSCB, dptNamesDCSC;
  dyn_dyn_int dptTypesPSPP, dptTypesSCB, dptTypesDCSC;
  string dpt_PSPP = "dcsc_PSPP";
  string dpt_SCB = "dcsc_SCB";
  string dpt_DCSController = "dcsc_DCSController";
  string opcuadatasub = "OPCUADATASUB";
  dyn_string dpts = makeDynString(dpt_PSPP, dpt_SCB, dpt_DCSController);
  dyn_string mdps = makeDynString("_mp_" + dpt_PSPP, "_mp_" + dpt_SCB, "_mp_" + dpt_DCSController);
  int i, j, ret = -1, n_scb, n_pspp, ch, reg, idx;
  string dpName, refdcsc, refscb, refpspp, refmonvals, refadcchs, refmonvals, refregs;
  string refdcscdp, refscbdp, refpsppdp, refmonvalsdp, refadcchsdp, refmonvalsdp, refregsdp;
  dyn_string monValsNames = makeDynString("Temperature", "Voltage1", "Voltage2");
  dyn_string opcuaRegNames = makeDynString("ChipID1", "ChipID2", "ADCR1", "ADCR2", "DIN", 
                                           "DOUT", "Bypass", "ADCmux", "ADCL1", "ADCL2",
                                           "Control", "BGHI", "BGLO");
  int ro = DPATTR_ADDR_MODE_IO_SPONT, rw = DPATTR_ADDR_MODE_INPUT_SPONT;
  dyn_int psppRegAttr = makeDynInt(ro, ro, ro, ro, ro, rw, rw, rw, ro, ro, rw, rw, rw);
  string opcuadrvdp = "dist_1:_DCSControllerServer";
  string reference;

  // Create data point type "dcsc_PSPP"
  dptNamesPSPP[1] = makeDynString("dcsc_PSPP", "", "");
  dptTypesPSPP[1] = makeDynInt(DPEL_STRUCT);
  dptNamesPSPP[2] = makeDynString("", "Status", "");
  dptTypesPSPP[2] = makeDynInt(0, DPEL_BOOL);
  dptNamesPSPP[3] = makeDynString("", "MonitoringData", "");
  dptTypesPSPP[3] = makeDynInt(0, DPEL_STRUCT);
  for(i = 4; i < 4 + dynlen(monValsNames); i++) {
    dptNamesPSPP[i] = makeDynString("", "", monValsNames[i - 3]);
    dptTypesPSPP[i] = makeDynInt(0, 0, DPEL_UINT);
  }
  idx = 4 + dynlen(monValsNames);
  dptNamesPSPP[idx] = makeDynString("", "Regs", "");
  dptTypesPSPP[idx] = makeDynInt(0, DPEL_STRUCT);
  idx += 1;
  for(i = idx; i < idx + dynlen(opcuaRegNames); i++) {
    sprintf(dpName, "%02d_" + opcuaRegNames[i - idx + 1], i - idx);
    dptNamesPSPP[i] = makeDynString("", "", dpName);
    dptTypesPSPP[i] = makeDynInt(0, 0, DPEL_UINT);
  }
  idx += dynlen(opcuaRegNames);
  dptNamesPSPP[idx] = makeDynString("", "ADCChannels", "");
  dptTypesPSPP[idx] = makeDynInt(0, DPEL_STRUCT);
  idx += 1;
  for(i = 0; i < 8; i++) {
    sprintf(dpName, "Ch%d", i);
    dptNamesPSPP[idx + i] = makeDynString("", "", dpName);
    dptTypesPSPP[idx + i] = makeDynInt(0, 0, DPEL_UINT);
  }
  ret = dptModify(dptNamesPSPP, dptTypesPSPP);
  DebugTN("dptModify(dptNamesPSPP, dptTypesPSPP) returned", ret);

  // Create data point type "dcsc_SCB"
  dptNamesSCB[1] = makeDynString("dcsc_SCB", "", "");
  dptTypesSCB[1] = makeDynInt(DPEL_STRUCT);
  dptNamesSCB[2] = makeDynString("", "ConnectedPSPPs", "");
  dptTypesSCB[2] = makeDynInt(0, DPEL_UINT);
  for(i = 0; i < 16; i++) {
    sprintf(dpName, "PSPP%d", i);
    dptNamesSCB[i + 3] = makeDynString("", dpName, "dcsc_PSPP");
    dptTypesSCB[i + 3] = makeDynInt(0, DPEL_TYPEREF);
  }
  ret = dptModify(dptNamesSCB, dptTypesSCB);
  DebugTN("dptModify(dptNamesSCB, dptTypesSCB) returned", ret);

  // Create data point type "dcsc_DCSController"
  dptNamesDCSC[1] = makeDynString("dcsc_DCSController", "", "");
  dptTypesDCSC[1] = makeDynInt(DPEL_STRUCT);
  dptNamesDCSC[2] = makeDynString("", "Status", "");
  dptTypesDCSC[2] = makeDynInt(0, DPEL_BOOL);
  for(i = 0; i < 4; i++) {
    sprintf(dpName, "SCB%d", i);
    dptNamesDCSC[i + 3] = makeDynString("", dpName, "dcsc_SCB");
    dptTypesDCSC[i + 3] = makeDynInt(0, DPEL_TYPEREF);
  }
  ret = dptModify(dptNamesDCSC, dptTypesDCSC);
  DebugTN("dptModify(dptNamesDCSC, dptTypesDCSC) returned", ret);

  // Create master data points
  DebugTN("Create master data points");
  for(i = 1; i <= dynlen(dpts); i++) {
    ret = dpCreate(mdps[i], dpts[i]);
    DebugTN("dpCreate('" + mdps[i] + "', '" + dpts[i] + "' returned", ret);
  }
  
  // Search internal data point of OPC server
  DebugTN("Search internal data point of OPC server ...");
  if(dpExists(opcuadrvdp)) {
    DebugTN("Found!");
  }
  else {
    DebugTN("... Not Found; exiting");
    exit();
  }

  // Check if server is running
  int connState;
  dpGet(opcuadrvdp + ".State.ConnState", connState);
  if(connState != 1) {
    DebugTN("OPCUA server is not connected. Make sure that the driver manager is running.");
    exit();
  }

  // Check if subscription exists
  DebugTN("Search subscription data point ...");
  if(!dpExists("_" + opcuadatasub)) {
    DebugTN("... Not found.");
    dyn_string subs = dpNames("*", "_OPCUASubscription");
    if(dynlen(subs) == 1) {
      DebugTN("Found only one OPCUA subscription and taking it as default data subscription.");
      opcuadatasub = strltrim(subs[1], "_");
    } else {
      DebugTN("Found more than one or no OPCUA data subscriptions; exiting.");
      exit();
    }
  } else {
    DebugTN("... Found.");
  }
  string refpre = "DCSControllerServer$" + opcuadatasub + "$1$2$/0:Objects/2:";
  
  // Remove existing data points
  for(i = 1; i <= 127; i++) {
    sprintf(dpName, "DCSController%d", i);
    if (dpExists(dpName)) {
      ret = dpDelete(dpName);
      if(ret == 0) {
        DebugTN("Deleted data point " + dpName);
      } else {
        DebugTN("Failed to delete data point" + dpName);
      }
    }
  }
  
  // Get separator, usually '.'
  string separator;
  dpGet(opcuadrvdp + ".Config.Separator:_original.._value", separator);
  DebugTN("Got separator:", separator);
  
  // Put together request id (arbitrary string)
  string requestId = myUiNumber() + "_ManId" + myManId() + "_manType" + myManType();
  DebugTN("Request Id:", requestId);
  
  // Get list available DCS Controllers on the server
  string getBranchdp = opcuadrvdp + ".Browse.GetBranch:_original.._value";
  string displayNamesdp = opcuadrvdp + ".Browse.DisplayNames";
  string nodeIdsdp = opcuadrvdp + ".Browse.NodeIds";
  string browsePathsdp = opcuadrvdp + ".Browse.BrowsePaths";
  dyn_string displayNames, nodeIds, browsePaths;
  // Set the browse data point to browse the top level node
  dpSet(getBranchdp, makeDynString(requestId, "ns=0;i=85", 1, 0));
  delay(1);   // Small delay to give the server time to respond
  // Read display names, browse paths and node ids of second-highest level
  dpGet(displayNamesdp, displayNames, browsePathsdp, browsePaths, nodeIdsdp, nodeIds);

  // Loop over all received display names
  for(i = 1; i <= dynlen(displayNames); i++) {
    // Search for correct names because there may be other objects on the bus
    if(strpos(displayNames[i], "DCSController") == 0) {
      DebugTN("Found DCS Controller:", browsePaths[i]);
      // Create data points from master data point
      dpCopy("_mp_dcsc_DCSController", displayNames[i], ret);

      if(ret == 0) {
        // Adjust address configs
        DebugTN("Created data point " + displayNames[i]);
        delay(1);
        refdcsc = refpre + displayNames[i];
        refdcscdp = displayNames[i];
        set_ref(refdcscdp + ".Status", refdcsc + "/2:Status", ro);
        
        // Loop over SCB masters
        for(n_scb = 0; n_scb < 4; n_scb++) {
          sprintf(refscb, "%s/2:SCB%d", refdcsc, n_scb);
          sprintf(refscbdp, "%s.SCB%d", refdcscdp, n_scb);
          set_ref(refscbdp + ".ConnectedPSPPs", refscb + "/2:ConnectedPSPPs", rw);
          
          // Loop over PSPPs at a given SCB master
          for(n_pspp = 0; n_pspp < 16; n_pspp++) {
            sprintf(refpspp, "%s/2:PSPP%d", refscb, n_pspp);
            sprintf(refpsppdp, "%s.PSPP%d", refscbdp, n_pspp);
            DebugTN("Data Point prefix:", refpsppdp);
            DebugTN("Reference Prefix:", refpspp);
            set_ref(refpsppdp + ".Status", refpspp + "/2:Status", ro);
            
            // Loop over monitoring values
            for(j = 1; j <= dynlen(monValsNames); j++) {
              refmonvals = refpspp + "/2:MonitoringData/2:" + monValsNames[j];
              refmonvalsdp = refpsppdp + ".MonitoringData." + monValsNames[j];
              set_ref(refmonvalsdp, refmonvals, ro);
            }

            // Loop over ADC channels
            for (ch = 0; ch < 8; ch++) {
              refadcchs = refpspp + "/2:ADCChannels/2:Ch" + ch;
              refadcchsdp = refpsppdp + ".ADCChannels.Ch" + ch;
              set_ref(refadcchsdp, refadcchs, ro);
            }

            // Loop over PSPP registers
            for(reg = 1; reg <= 13; reg++) {
              refregs = refpspp + "/2:Regs/2:" + opcuaRegNames[reg];
              sprintf(refregsdp, refpsppdp + ".Regs.%02d_" + opcuaRegNames[reg], reg - 1);
              set_ref(refregsdp, refregs, psppRegAttr[reg]);
            }
          }  // End of PSPP for loop
        }  // End of SCB for loop
      } else {
        DebugTN("Failed to create data point " + displayNames[i]);
      }  // End of data point creation if
    }  // End of found DCS Controller on server if
  }  // End of for loop over display names
}  // End of main()

/**
  Set the '_address' attribute of a data point to be an OPCUA connection

  This function enables Old/New comparison and sets datatype conversion to default.

  @param dp: Name of the data point which shall be modified
  @param ref: Reference string, encoding the OPCUA item
  @param direction: If this input only or I/O. One can use predefined constants or the values 2 and
    6 respectively.
*/
int set_ref(string dp, string ref, int direction)
{
  int ret, ret1, ret2;
  string dpAddress = dp + ":_address..";
  ret = dpSetWait(dpAddress + "_type", 16,
                  dpAddress + "_drv_ident", "OPCUA",
                  dpAddress + "_datatype", 750,
                  dpAddress + "_direction", direction,
                  dpAddress + "_lowlevel", TRUE,
                  dpAddress + "_reference", ref,
                  dpAddress + "_active", TRUE);
  return ret;
}

/**
  Create or update a data point type (DPT)

  @param names: Contains the names of all nodes. The position in the sub-can_string defines the
    structure of the dpt.
  @param types: Contains type definitions of all nodes as WinCC OA constants such as DPEL_BOOL. The
    length and position of these constants in its elements must match the structure defined in
    'names'.
  @return 0 if good and -1 in case of errors
*/
int dptModify(dyn_dyn_string names, dyn_dyn_int types)
{
  int ret, getdpt;
  dyn_dyn_string n; // Dummy variable
  dyn_dyn_int t;    // Dummy variable
  string dpt = names[1][1];

  DebugTN("Creating or updating data point type " + dpt);
  getdpt = dpTypeGet(dpt, n, t);
  if(getdpt == 0) {
    DebugTN("DPT " + dpt + " already exists.");
    ret = dpTypeChange(names, types);
  }
  else {
    DebugTN("DPT " + dpt + " does not exist. I will now create it.");
    ret = dpTypeCreate(names, types);
  }

  return ret;
}

