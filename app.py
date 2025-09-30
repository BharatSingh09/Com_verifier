from flask import Flask, render_template, request, session, redirect, url_for
import csv, io, re
import tempfile, os
import webview
import threading
import sys

app = Flask(__name__)
app.secret_key = "supersecret"

pattern_1 = re.compile(r'appConfig.s4lgcConfig.routes\[(\d+)U\]\.distEntryExitSignal')
pattern_2=re.compile(r'appConfig.s4lgcConfig.routes\[(\d+)U\]\.ssp\.speedInfo\[(\d+)U\]\.dist')
pattern_3=re.compile(r'appConfig.s4lgcConfig.routes\[(\d+)U\]\.entrySigTagId')
Span_pattern=re.compile(r'appConfig.aggrProfConfiguration.trackProf\[(\d+)U\]\.profSpan')
pattern_6=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.tagId')
my_dict={
    1:(16,pattern_1),
    2:(34,pattern_2),
    3:(15,pattern_3),
    6:(0,pattern_6)
}
# Dist Verifier
def load_csv1(file,index):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    rows = list(reader)
    cleaned_data = []
    for row in rows[1:]:
        if not row or not row[0].strip().isdigit():
            continue
        # Create a list of values based on the column indices
        data = [row[0].strip() if 0 < len(row) else '' ] 
        data.append(row[index].strip() if index < len(row) else '')
        # Append the list to the cleaned_data list
        cleaned_data.append(data)
    return cleaned_data

def load_csv2_1(file,pattern):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    mapping={}
    for idx,row in enumerate(reader):
        if len(row) < 4:
            continue
        match=pattern.search(row[0])
        if match:
            sno = int(match.group(1)) + 1
            try:
                value = row[3].strip()
                if sno in mapping:
                    mapping[sno] = (mapping[sno][0], mapping[sno][1] + int(value))  # (idx+1, sum of values)
                else:
                    mapping[sno] = (idx + 1, int(value))
            except ValueError:
                pass
    return mapping

def C_DistB2Sig(data1,data2):
    results = []
    i=0
    L=min(len(data1),len(data2))
    while i<L:
        if int(data1[i][0])==list(data2)[i]:
            Sno=data1[i][0]
            csv_1val=data1[i][1].replace(' ','')
            csv_2val=data2[i+1][1]
            match_status='Match' if int(csv_1val)==csv_2val else 'Mismatch'
            results.append({
                'S.No': Sno,
                'CSV1_Value': csv_1val,
                'Index': data2[i+1][0],
                'CSV2_Value': csv_2val,
                'Status': match_status,
            })
        else:
            a=1 if int(data1[i][0])<list(data2)[i] else 2
            if a==1:
                Sno=data1[i][0]
                csv_1val=data1[i][1].replace(' ','')
                match_status='Missing'
                results.append({
                    'S.No': Sno,
                    'CSV1_Value': csv_1val,
                    'Index':'No Data',
                    'CSV2_Value': 'No Data',
                    'Status': match_status,
                })
            else:
                Sno=list(data2)[i]
                csv_2val=data2[i+1][1].replace(' ','')
                match_status='Missing'
                results.append({
                    'S.No': Sno,
                    'CSV1_Value': 'No Data',
                    'Index': data2[i+1][0],
                    'CSV2_Value': csv_2val,
                    'Status': match_status,
                })
        i+=1

    while i<len(data1):
        Sno=data1[i][0]
        csv_1val=data1[i][1].replace(' ','')
        csv_2val="No Data"
        match_status='Missing'
        results.append({
            'S.No': Sno,
            'CSV1_Value': csv_1val,
            'Index': 'NO Data',
            'CSV2_Value': csv_2val,
            'Status': match_status,
        })
        i+=1
    while i<len(list(data2)):
        Sno=i+1
        csv_1val="No Data"
        csv_2val=data2[i+1][1]
        match_status='Missing'
        results.append({
            'S.No': Sno,
            'CSV1_Value': csv_1val,
            'Index': data2[i+1][0],
            'CSV2_Value': csv_2val,
            'Status': match_status,
        })
        i+=1
    return results
#end

# Rfid Verifier
def load_csv2_2(file, pattern):
    mapping = {}
    reader = list(csv.reader(io.StringIO(file.read().decode('utf-8'))))

    i = 0
    while i < len(reader):
        row = reader[i]
        if len(row) < 4:
            i += 1
            continue

        match = pattern.search(row[0])
        if match:
            sno = int(match.group(1)) + 1
            sub_pattern_1 = re.compile(rf'appConfig.s4lgcConfig.routes\[{sno-1}U\]\.enRouteTags\[(\d+)U\]\.linkDistance')
            sub_pattern_2=re.compile(rf'appConfig.s4lgcConfig.routes\[{sno-1}U\]\.enRouteTags\[(\d+)U\]\.tagId')
            # scan next rows until mismatch
            j = i + 2
            while j < len(reader):
                row2 = reader[j]
                sub_match_1 = sub_pattern_1.search(row2[0])
                sub_match_2 = sub_pattern_2.search(reader[j+1][0])
                if not  sub_match_1 or not sub_match_2:
                    break   # stop at first non-matching row

                #tag_idx = int(sub_match_1.group(1))
                value=row2[3]
                id=reader[j+1][3]
                if id=='0':
                    break
                if sno in mapping:
                    mapping[sno][0].append(j+1)
                    mapping[sno][1].append(value)
                    mapping[sno][2].append(id)
                else:
                    mapping[sno] = ([j+1], [value],[id])
                j += 2

            # skip ahead
            i = j
        else:
            i += 1
    return mapping

def C_Rfid(csv1_data,csv2_data):
    results = []

    for row in csv1_data:
        try:
            sno = int(row[0])  # Get S.No from the first column
            csv1_val = row[1].strip()
            csv1_val = row[1].replace(' ','')
            csv1_val = csv1_val.split(")#(")


            line_no, dist, id = csv2_data.get(sno, ([], [], []))  # Use empty lists if not found

            for i in range(len(csv1_val)):
                csv1_value = csv1_val[i].replace('(', '').replace(')', '')
                csv1_parts = csv1_value.split('#')

                csv1_item_1 = csv1_parts[0] if len(csv1_parts) > 0 else 'Invalid'
                csv1_item_2 = csv1_parts[1] if len(csv1_parts) > 0 else 'Invalid'
                # Default values if index out of range
                index_val = line_no[i] if i < len(line_no) else 'Missing'
                dist_val = dist[i] if i < len(dist) else 'Missing'
                id_val=id[i] if i < len(id) else 'Missing'

                # Determine match status
                if i < len(dist) and dist[i] is not None:
                    match_status = 'Match' if csv1_item_1 == dist[i] else 'Mismatch'
                else:
                    match_status = 'Missing'

                results.append({
                    'S.No': sno,
                    'CSV1_Dist': csv1_item_1,
                    'CSV1_RFID':csv1_item_2,
                    'Index': index_val,
                    'CSV2_Dist': dist_val,
                    'CSV2_RFID':id_val,
                    'Status': match_status
                })
        except Exception as e:
            print(f"Exception: {e}")
            pass
    return results
#end

#Span Verifier
def span_csv1(file,index):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    rows = list(reader)
    cleaned_data = []
    a=-1
    for row in rows[2:]:
        if not row or not row[0].strip().isdigit():
            if row[index].strip().isdigit():
                cleaned_data[a][1]+=int(row[index])
            continue
        # Create a list of values based on the column indices
        data = [row[0].strip() if 0 < len(row) else '' ] 
        data.append(int(row[index].strip()) if (index < len(row)) and (row[index].strip().isdigit()) else '')
        # Append the list to the cleaned_data list
        cleaned_data.append(data)
        a+=1
    return cleaned_data
def compare_data_3(csv1_data, csv2_data_1,csv2_data_2):
    results = []
    column_index=1
    for row in csv1_data:
        try:
            sno = int(row[0])  # Get S.No from the first column
            csv1_val = row[column_index] if row[column_index] else 0
            index_1, csv2_val_1 = csv2_data_1.get(sno, (None, None))
            index_2, csv2_val_2 = csv2_data_2.get(sno, (None, None))
            match_status = 'Match' if (csv2_val_1 == csv1_val) and  (csv2_val_1 == csv2_val_2) else 'Mismatch'
            results.append({
                'S.No': sno,
                'CSV1_Value': csv1_val,
                'Index_1': index_1,
                'CSV2_Value_1': csv2_val_1 if csv2_val_1 is not None else 'Not Found',
                'Index_2':index_2,
                'CSV2_Value_2': csv2_val_2 if csv2_val_2 is not None else 'Not Found',
                'Status': match_status if csv2_val_1 is not None else 'Missing in CSV2'
            })
        except (ValueError, KeyError, IndexError):  # Handle missing or incorrect data
            results.append({
                'S.No': row[0] if len(row) > 0 else 'Unknown',  # Assuming 'S.No' is in the first column
                'CSV1_Value': row[column_index] if len(row) > column_index else 'Invalid',  # Handle invalid data
                'CSV2_Value': 'Error',
                'Status': 'Error'
            })
    return results
#end

# Rat Verifier
def Rat_csv1(file):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    rows = list(reader)

    # Remove header
    if rows:
        del rows[0]

    cleaned_rows = []
    for row in rows:
        if len(row) < 8:  # need at least 8 cols since you delete up to index 7
            #print(f"Skipping row with only {len(row)} columns: {row}")
            continue

        # Delete in reverse order so indexes don’t shift
        for idx in [7, 6, 2, 0]:
            del row[idx]

        cleaned_rows.append(row)

    return cleaned_rows

def Rat_csv2(file):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    rows = list(reader)
    result=[]
    for i in range(0,len(rows)):
        pattern=re.compile('appConfig.fldinConfig.nRelays')
        match=pattern.search(rows[i][0])
        if match:
            relay_no=rows[i][3]
            i+=1
            while i<len(rows):
                relayid = re.compile(r'appConfig\.fldinConfig\.relay2Obj\[(\d)+U\]\.relayId')
                riuid   = re.compile(r'appConfig\.fldinConfig\.relay2Obj\[(\d)+U\]\.riuId')
                slot    = re.compile(r'appConfig\.fldinConfig\.relay2Obj\[(\d)+U\]\.slot')
                port    =re.compile(r'appConfig\.fldinConfig\.relay2Obj\[(\d+)U\]\.port')
                relay_match=relayid.search(rows[i][0])
                if relay_match:
                    relay_val=rows[i][3]
                    i+=1
                else:
                    relay_val='Not found'
                riuid_match=riuid.search(rows[i][0])
                if riuid_match:
                    riuid_val=rows[i][3]
                    i+=1
                else:
                    riuid_val='Not found'
                slot_match=slot.search(rows[i][0])
                if slot_match:
                    slot_val=rows[i][3]
                    i+=1
                else:
                    slot_val='Not found'
                port_match=port.search(rows[i][0])
                if port_match:
                    port_val=rows[i][3]
                    i+=1
                else:
                    port_val='Not found'
                sub_list=[relay_val,riuid_val,slot_val,port_val]
                result.append(sub_list)

                if (int(port_match.group(1)) + 1)==int(relay_no):
                    return result
    return result

def compare_Rat_data(df1,df2):
    len_val = max(len(df1), len(df2)) 
    results=[]    
    for i in range(0,len_val):
        if i>=len(df1):
            df1_relayid='No Data'
            df1_riuid='No Data'
            df1_slot='No Data'
            df1_port='No Data'
        else:
            df1_relayid=df1[i][0]
            df1_riuid=df1[i][1]
            df1_slot=df1[i][2]
            df1_port=df1[i][3]
        if i>=len(df2):
            df2_relayid='No_Data'
            df2_riuid='No_Data'
            df2_slot='No_Data'
            df2_port='No_Data'
        else:
            df2_relayid=df2[i][0]
            df2_riuid=df2[i][1]
            df2_slot=df2[i][2]
            df2_port=df2[i][3]

        match_status='Match'if (df1_relayid==df2_relayid) and (df1_riuid==df2_riuid) and (df1_slot==df2_slot) and (df1_port==df2_port) else 'Mismatch'
        results.append({
            'CSV1_RelayID':df1_relayid,
            'CSV1_RIUID':df1_riuid,
            'CSV1_SLOT':df1_slot,
            'CSV1_PORT':df1_port,
            'CSV2_RelayID':df2_relayid,
            'CSV2_RIUID':df2_riuid,
            'CSV2_SLOT':df2_slot,
            'CSV2_PORT':df2_port,
            'Status': match_status
        })
    return results
# end


# A tag Verifier
def Atag_csv1(file):
    reader = csv.reader(io.StringIO(file.read().decode('utf-8')))
    rows = list(reader)

    headers = rows[0]
    cleaned_data = []
    for row in rows[1:]:
        if not row or not row[0].strip().isdigit():
            continue
        
        # Create a list of values based on the column indices
        data = [row[idx].strip() if idx < len(row) else '' for idx in range(len(headers))]
        
        # Append the list to the cleaned_data list
        cleaned_data.append(data)
    
    return cleaned_data

def extract_csv1(cleaned_data):
    mapping={}
    for i in cleaned_data:
        adj_info=i[19]
        adj_info=adj_info.replace('(','').replace(')','').replace(' ','')
        adj_info=adj_info.split('#')
        if adj_info[0]=='1':
            tag=''
            dist=int(adj_info[1])
            dom=adj_info[2]
            absloc=adj_info[3]
            seq=i[15].replace(' ','')
            seq=seq.split(')#(')
            match_dist=0
            for j in seq:
                j=j.replace('(','').replace(')','').replace(' ','')
                j=j.split('#')
                match_dist+=int(j[0])
                if match_dist==dist:
                        tag=j[1].replace('R-','')
                        tag=str(int(tag))
            tin=i[20].replace(' ','')
            tin=tin.replace('(','').replace(')','')
            tin=tin.split('#')
            if len(tin)>=2:
                tinN=tin[1]
                tinR=tin[1]
            else:
                tinN="Not Data"
                tinR="Not Data"
            mapping[tag]=(absloc,dom,tinN,tinR)
    return mapping

def Atag_csv2(reader,df1,pattern):
    mapping = {} 
    for i in range(0,len(reader)):
        match=pattern.search(reader[i][0])
        key=reader[i][3]
        if match and (key in df1):
            mapping[key]={}
            type_pattern=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.tagType')
            absLoc_pattern=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.absLoc')
            DOM_pattern=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.permissibleDoM')
            tinN_pattern=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.tinNom')
            tinR_pattern=re.compile(r'appConfig.s4lgcConfig.augTLI\[(\d+)U\]\.tinRev')
            if type_pattern.search(reader[i+1][0]):
                mapping[key]['tagType']=reader[i+1][3]
            else:
                mapping[key]['tagType']='Not Data'
            if absLoc_pattern.search(reader[i+2][0]):
                mapping[key]['absLoc']=reader[i+2][3]
            else:
                mapping[key]['absLoc']='Not Data'
            if DOM_pattern.search(reader[i+3][0]):
                mapping[key]['permissibleDoM']=reader[i+3][3]
            else:
                mapping[key]['permissibleDoM']='Not Data'
            if tinN_pattern.search(reader[i+5][0]):
                mapping[key]['tinNom']=reader[i+5][3]
            else:
                mapping[key]['tinNom']='Not Data'
            if tinR_pattern.search(reader[i+6][0]):
                mapping[key]['tinRev']=reader[i+6][3]
            else:
                mapping[key]['tinRev']='Not Data'
            i+=6
        end_pattern=re.compile(r'appConfig.s4lgcConfig.nSigParams')
        if end_pattern.search(reader[i][0]):
            break
    return mapping

def Atag_compare(df1,df2):
    result=[]
    for i in df1:
        match_status='Match' if (df2[i]['tagType']=='12') and (df1[i][0]==df2[i]['absLoc']) and (df1[i][1]==df2[i]['permissibleDoM']) and (df1[i][2]==df2[i]['tinNom']) and (df1[i][3]==df2[i]['tinRev']) else 'Mismatch'
        match_status='Match' if (df2[i]['tagType']=='12') else 'Mismatch'
        result.append({
            'Name':'Name',
            'Input':i,
            'Config':i,
            'Status': 'Match'
        })
        result.append({
            'Name':'TAG_Type',
            'Input':'12',
            'Config':df2[i]['tagType'],
            'Status': match_status
        })
        match_status='Match' if (df1[i][0]==df2[i]['absLoc']) else 'Mismatch'
        result.append({
            'Name':'ABS_LOC',
            'Input':df1[i][0],
            'Config':df2[i]['absLoc'],
            'Status': match_status
        })
        match_status='Match' if (df1[i][1]==df2[i]['permissibleDoM']) else 'Mismatch'
        result.append({
            'Name':'DOM',
            'Input':df1[i][1],
            'Config':df2[i]['permissibleDoM'],
            'Status': match_status
        })
        match_status='Match' if (df1[i][2]==df2[i]['tinNom']) else 'Mismatch'
        result.append({
            'Name':'TinN',
            'Input':df1[i][2],
            'Config':df2[i]['tinNom'],
            'Status': match_status
        })
        match_status='Match' if (df1[i][3]==df2[i]['tinRev']) else 'Mismatch'
        result.append({
            'Name':'TinR',
            'Input':df1[i][3],
            'Config':df2[i]['tinRev'],
            'Status': match_status
        })
    return result
# end

# Tli Enco/Deco
def hextoBinary(hex_str):
    binary_data = bytes.fromhex(hex_str.replace(" ", ""))
    bitstream = ''.join(bin(b)[2:].zfill(8) for b in binary_data)
    return bitstream

def bits(bit,idx):
    return bit[:idx],bit[idx:]

def binToDec(binary):
    return int(binary, 2)

def decodeHex(hex_str):
    bit=hextoBinary(hex_str.strip())
    subPktType,bit=bits(bit,4)
    subPktType=binToDec(subPktType)
    subPktLen,bit=bits(bit,7)
    subPktLen=binToDec(subPktLen)+1
    disDupTag,bit=bits(bit,4)
    disDupTag=binToDec(disDupTag)
    rutRfidCnt,bit=bits(bit,6)
    rutRfidCnt=binToDec(rutRfidCnt)
    RFID_Dist=[]
    RFID_Id=[]
    DupTagDir=[]
    for i in range(0,rutRfidCnt):
        dstNxtRfid,bit=bits(bit,11)
        dstNxtRfid=binToDec(dstNxtRfid)
        RFID_Dist.append(dstNxtRfid)
        nxtRfidId,bit=bits(bit,10)
        nxtRfidId=binToDec(nxtRfidId)
        RFID_Id.append(nxtRfidId)
        dupTagDir,bit=bits(bit,1)
        dupTagDir=binToDec(dupTagDir)
        DupTagDir.append(dupTagDir)
    absLocRst,bit=bits(bit,1)
    absLocRst=binToDec(absLocRst)
    StrToRst=[]
    AdjLoco=[]
    AbsCotn=[]
    for i in range(0,absLocRst):
        srtToLocRst,bit=bits(bit,15)
        srtToLocRst=binToDec(srtToLocRst)
        StrToRst.append(srtToLocRst)
        adjLocoDir,bit=bits(bit,2)
        adjLocoDir=binToDec(adjLocoDir)
        AdjLoco.append(adjLocoDir)
        absLocCrn,bit=bits(bit,23)
        absLocCrn=binToDec(absLocCrn)
        AbsCotn.append(absLocCrn)
    adjLnCnt,bit=bits(bit,3)
    adjLnCnt=binToDec(adjLnCnt)
    LinTin=[]
    for i in range(0,(adjLnCnt)+1):
        lnTin,bit=bits(bit,9)
        lnTin=binToDec(lnTin)
        LinTin.append(lnTin)
    return subPktType,subPktLen,disDupTag,rutRfidCnt,RFID_Dist,RFID_Id,DupTagDir,absLocRst,StrToRst,AdjLoco,AbsCotn,adjLnCnt,LinTin

def Tli_E_csv2(reader,Routes):
    mapping = {}
    i=0
    K=0

    while (i < len(reader)) and (K<Routes):

        pattern=re.compile(rf'appConfig.s4lgcConfig.routes\[{K}U\]\.tli.subPktType')
        match=pattern.search(reader[i][0])
        if match:
            sub_pattern=re.compile(rf'appConfig.s4lgcConfig.routes\[{K}U\]\.tli.adjLines')
            sub_pattern_2=re.compile(rf'appConfig.s4lgcConfig.routes\[{K}U\]\.tli.adjTins\[(\d+)U\]')
            K+=1
            j=i
            while j < len(reader) and not sub_pattern.search(reader[j][0]):
                key=reader[j][0].split('.')
                key=key[len(key)-1]
                key=re.sub(r'\[\d+U\]', '', key)
                if K in mapping:
                    if key in mapping[K]:
                        mapping[K][key]+=","+reader[j][3]
                    else:
                        mapping[K][key]=reader[j][3]
                else:
                    mapping[K]={key:reader[j][3]}
                j+=1
            tli_count=int(reader[j][3])+1
            key=reader[j][0].split('.')
            key=key[len(key)-1]
            key=re.sub(r'\[\d+U\]', '', key)
            mapping[K][key]=reader[j][3]
            j+=1
            for n in range(0,tli_count):
                if sub_pattern_2.search(reader[j][0]):
                    key=reader[j][0].split('.')
                    key=key[len(key)-1]
                    key=re.sub(r'\[\d+U\]', '', key)
                    if K in mapping:
                        if key in mapping[K]:
                            mapping[K][key]+=","+reader[j][3]
                        else:
                            mapping[K][key]=reader[j][3]
                    else:
                        mapping[K]={key:reader[j][3]}
                    j+=1
                else:
                    break
            i=j-1
        i+=1
    return mapping,i

def match_DE(map2,map3):
    result={}
    subPktType,subPktLen,dupTagDist,rfidCount,nxtRfidDist,nxtRfidId,dupTagDir,absLocReset,startDistToReset,newLocoDir,absLocCorrection,adjLines,adjTins=decodeHex(map3[2])
    for key, val in map2.items():
        if key in locals():  # check if variable exists
            var_val = locals()[key]
            if isinstance(var_val, list):
                # join list elements as strings with commas
                var_str = ",".join(map(str, var_val))
            else:
                var_str = str(var_val)
            if var_str=='':
                var_str='0'
            match = (val == var_str)
            if match:
                result[key]=[val,var_str,'match']
            else:
                result[key]=[val,var_str,'mismatch']
        else:
            result[key]=['not found','not fond','missing']
    return result

def Tli_D_csv2(reader,Routes):
    mapping = {}
    i=0
    K=0
    while (i < len(reader)) and (K<Routes):
        pattern=re.compile(rf'appConfig.aggrProfConfiguration.tliProf\[{K}U\]\.tliProfId')
        match=pattern.search(reader[i][0])
        if match:
            ProfId=reader[i][3]
            i+=1
            Len_match=re.compile(rf'appConfig.aggrProfConfiguration.tliProf\[{K}U\]\.tliLen').search(reader[i][0])
            if Len_match:
                Len=reader[i][3]
                i+=1
                Data_match=re.compile(rf'appConfig.aggrProfConfiguration.tliProf\[{K}U\]\.tliData').search(reader[i][0])
                if Data_match:
                    Data=reader[i][3].strip().replace(" ",'') 
                    end=2*int(Len)
                    Data=Data[:end]
                    K+=1
                    mapping[K]=(ProfId,Len,Data)
                else:
                    mapping[K]=["Data Not Found",i]
            else:
                mapping[K]=["Len Not Found",i]
        i+=1
    return mapping,i

def compare_Tli_Enco_Deco(map_2,map_3,df):
    results2=[]
    for i in range(0,len(df)):
        sno=df[i][0]
        map2=map_2[int(sno)]
        map3=map_3[int(sno)]
        sec_tabel=match_DE(map2,map3)

        for data in sec_tabel:
            results2.append({
                'S.No': sno,
                'Name':data,
                'Encoded':sec_tabel[data][0],
                'Decoded':sec_tabel[data][1],
                'Status':sec_tabel[data][2],
            })
    return results2
#end


@app.route('/', methods=['GET', 'POST'])
def main():
    results = []

    if request.method == 'POST':
        if "new_file" in request.form:
            session.clear()
            return redirect(url_for('main'))

        csv1_file = request.files.get('csv1_file')
        csv2_file = request.files.get('csv2_file')
        order= request.form.get('selected')
        if csv1_file:
            temp1 = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
            csv1_file.save(temp1.name)
            session['csv1_path'] = temp1.name

        if csv2_file:
            temp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
            csv2_file.save(temp2.name)
            session['csv2_path'] = temp2.name

        if 'csv1_path' not in session or 'csv2_path' not in session:
            return render_template("index.html", error="Please provide both CSV", session=session)
        if order is None:
            return render_template("index.html", error="Please select a Function", session=session)
        order=int(order)
        if order==1:
            index,pattern=my_dict[order]
            with open(session['csv1_path'], "rb") as f1:
                data1=load_csv1(f1,index)
            with open(session['csv2_path'], "rb") as f2:
                data2=load_csv2_1(f2,pattern)
            results=C_DistB2Sig(data1,data2)
        elif order==2:
            index,pattern=my_dict[order]
            with open(session['csv1_path'], "rb") as f1:
                data1=span_csv1(f1,index)
            with open(session['csv2_path'], "rb") as f2:
                data2=load_csv2_1(f2,pattern)
                f2.seek(0)
                data_2 = load_csv2_1(f2,Span_pattern)
            results=compare_data_3(data1, data2,data_2)
        elif order==3:
            index,pattern=my_dict[order]
            with open(session['csv1_path'], "rb") as f1:
                data1=load_csv1(f1,index)
            with open(session['csv2_path'], "rb") as f2:
                data2=load_csv2_2(f2, pattern)
            results=C_Rfid(data1,data2)
        elif order==4:
            with open(session['csv1_path'], "rb") as f1:
                df1 = load_csv1(f1,15)
                Routes = len(df1)
            with open(session['csv2_path'], "r", encoding="utf-8") as f2:
                rows = list(csv.reader(f2))
                map_2, index = Tli_E_csv2(rows, Routes)
                map_3, index = Tli_D_csv2(rows, Routes)
            results= compare_Tli_Enco_Deco(map_2, map_3, df1)
        elif order==5:
            with open(session['csv1_path'], "rb") as f1:
                data1=Rat_csv1(f1)
            with open(session['csv2_path'], "rb") as f2:
                data2=Rat_csv2(f2)
            results=compare_Rat_data(data1,data2)
        elif order==6:
            index,pattern=my_dict[order]
            with open(session['csv1_path'], "rb") as f1:
                data1=Atag_csv1(f1)
                df1=extract_csv1(data1)
            with open(session['csv2_path'], "r", encoding="utf-8") as f2:
                rows = list(csv.reader(f2))
                data2=Atag_csv2(rows,df1,pattern)
            print(df1)
            print(data2)
            results=Atag_compare(df1,data2)
            if len(results)==0:
                results=[{'Status':'No Match Found'}]
        else:
            return render_template("index.html", error="Wrong Type Selected", session=session)
    
    return render_template("index.html", result_data=results, session=session)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return "Server shutting down..."

def start_flask():
    app.run(host="127.0.0.1", port=7363, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Start Flask in background
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Create the desktop window
    window = webview.create_window("My Flask App", "http://127.0.0.1:7363/", width=1000, height=700)

    # When window closes → also shut down Flask
    def on_closed():
        try:
            import requests
            requests.post("http://127.0.0.1:7363/shutdown")
        except:
            pass
        sys.exit(0)

    webview.start(on_closed, window)



