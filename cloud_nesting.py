import http.server
import webbrowser
import urllib.parse
import urllib.request
import json
import time
import threading

script = """
/**
 * CAM Additive Sample
 * Creates an Additive setup out of the bodies in the Fusion's Design Workspace.
 * @param {string} hubId The id of the hub to load files from.
 *                       Use data.property in Fusion text commands to get Hub Id.
 * @param {string} fileURN The id (urn) of the file, which you would like to convert into Additive Setup.
 *                                 Use data.property in Fusion to get Lineage Urn.
 * "machine": {
        "vendor": "HP",
        "model": "MJF 4200"
    },
    "printsetting": "HP - MJF"
 */

import { adsk } from "@adsk/fas";

function defaultFolder(app: adsk.core.Application, defaultProjectName: string) {
  const projects = app.data.activeHub.dataProjects;
  if (!projects) throw Error("Unable to get active hub's projects.");
  for (let i = 0; i < projects.count; ++i) {
    const project = projects.item(i)!;
    if (project.name === defaultProjectName) {
      return project.rootFolder;
    }
  }
  adsk.log(`Creating new project: ${defaultProjectName}`);
  const project = projects.add(defaultProjectName);
  if (!project) throw Error("Unable to create new project.");
  return project.rootFolder;
}

function generateRandomString(length: number): string {
  const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
      const randomIndex = Math.floor(Math.random() * characters.length);
      result += characters[randomIndex];
  }
  return result;
}

function uploadFile(app: adsk.core.Application,
  fileName: string
): adsk.core.DataFile
{
  let folder = defaultFolder(app, "Design Automation for Fusion");

  adsk.log("uploading file")
  let uploadFuture = folder.uploadFile(fileName)
  
  adsk.log("upload started")
  while (uploadFuture.uploadState == adsk.core.UploadStates.UploadProcessing) {
    // adsk.log(".")
    wait(1000)
  }
  if (uploadFuture.uploadState != adsk.core.UploadStates.UploadFinished) {
    adsk.log("Upload Failed")
    throw "Upload Failed";
  }
  const uploadedDataFile = uploadFuture.dataFile
  adsk.log("uploadedDataFile.name is " + uploadedDataFile.name)
  uploadedDataFile.name = "input_" + generateRandomString(10) + fileName
  adsk.log("Changed name to " + uploadedDataFile.name)
  return uploadedDataFile
}

function run() {
  // Read the parameters passed with the script
  const scriptParameters = JSON.parse(adsk.parameters);
  if (!scriptParameters) throw Error("Invalid parameters provided.");

  // Get the Fusion API's application object
  const app = adsk.core.Application.get();
  if (!app) throw Error("No asdk.core.Application.");

  // Log some information
  adsk.log(new Date().toString());
  // adsk.log("UserName: " + app.userName);
  // adsk.log("User: " + app.currentUser.displayName);
  // adsk.log("UserID: " + app.userId);
  adsk.log("Fusion Version: " + app.version);

  let fileName = scriptParameters.fileName;
  // if (scriptParameters.fileURN) {
  //   downloadDataFile(app, scriptParameters.hubId, scriptParameters.fileURN, fileName)
  // }
  // adsk.log(`Content of ${fileName} = ${adsk.readFileSync(fileName)}`)
  // let dataFile = uploadFile(app, fileName)
  // let dataFile = findFile(app, scriptParameters.hubId, scriptParameters.fileURN)
  let dataFile = findFile(app, null, scriptParameters.fileURN)

  adsk.log(`Opening file ${dataFile.name} ...`);
  let doc = app.documents.open(dataFile, true);
  doc.name = fileName;
  adsk.log(`doc.name = ${doc.name}`)

  // Switch to CAM Environment
   const camWS = app.userInterface.workspaces.itemById("CAMEnvironment");
   camWS?.activate();

  // Getting CAM Product
  const camProduct = doc.products.itemByProductType("CAMProductType");
  if (!camProduct) throw Error("File has no CAM Product.");
  const cam = camProduct as adsk.cam.CAM;

  adsk.log("Creating Manufacturing Model");
  const manufacturingModels = cam.manufacturingModels;
  const mmInput = manufacturingModels.createInput();
  mmInput.name = "Manufacturing Model";
  const manufacturingModel = manufacturingModels.add(mmInput);

  // adsk.log("Getting Occurences...");
  const occs = getValidOccurences(manufacturingModel.occurrence);
  if (occs.length == 0) {
    adsk.log("No component has been added to the scene. Terminating...");
    return;
  } else {
    // adsk.log(`Found ${occs.length} components`);
  }
  // Define and create the arrange operation
  adsk.log("Creating additive setup...");
  const setup = createAdditiveSetup(occs, cam,
    scriptParameters.machine.vendor, scriptParameters.machine.model,
    scriptParameters.printsetting);
  adsk.log("Creating additive arrange...");
  const arrangeInput = setup.operations.createInput("additive_arrange");

  // Modifying the parameters to control the arrangement. Units in centimeters
  // Can also be done similar to the Desktop API
  (<adsk.cam.StringParameterValue>(
    arrangeInput.parameters.itemByName("arrange_arrangement_type")?.value
  )).value = "Pack3D_TrueShape";
  (<adsk.cam.IntegerParameterValue>(
    arrangeInput.parameters.itemByName("arrange_platform_clearance")?.value
  )).value = 0.01; // fails with 0
  (<adsk.cam.FloatParameterValue>(
    arrangeInput.parameters.itemByName("arrange_frame_width")?.value
  )).value = 0.3;
  (<adsk.cam.FloatParameterValue>(
    arrangeInput.parameters.itemByName("arrange_ceiling_clearance")?.value
  )).value = 0.3;
  (<adsk.cam.IntegerParameterValue>(
    arrangeInput.parameters.itemByName("arrange_object_spacing")?.value
  )).value = .3;
  (<adsk.cam.IntegerParameterValue>(
    arrangeInput.parameters.itemByName("arrange_voxelsize")?.value
  )).value = .2;

  if (scriptParameters.quantity) {
    adsk.log(`Setting quantity to ${scriptParameters.quantity}`);
    (<adsk.cam.BooleanParameterValue>(
      arrangeInput.parameters.itemByName("arrange_quantity_group")?.value
    )).value = true;
    (<adsk.cam.IntegerParameterValue>(
      arrangeInput.parameters.itemByName("arrange_global_quantity")?.value
    )).value = scriptParameters.quantity;
  }

  const arrange = setup.operations.add(arrangeInput);
  adsk.log("Additive arrange: generating");
  let future = cam.generateToolpath(arrange);
  while (future.isGenerationCompleted == false) {
    wait(1000);
    // adsk.log(".")
  }
  adsk.log("Additive arrange added");
  saveDocument(
    doc,
    true,
    `${doc.name} nested ${scriptParameters.quantity}`,
    `Nested ${scriptParameters.quantity} copies`,
    dataFile.parentFolder,
  );

   while (app.hasActiveJobs) {
    wait(1000);
    // adsk.log(".")
  }
  adsk.log(`doc.dataFile.id = ${doc.dataFile.id}`)
  const result = {"datafile.id" : doc.dataFile.id, "fusionWebURL": doc.dataFile.fusionWebURL};
  
  adsk.result = JSON.stringify(result);
}

// Create an additive setup
function createAdditiveSetup(
  models: adsk.fusion.Occurrence[],
  cam: adsk.cam.CAM,
  vendor: string,
  model: string,
  printsettingName: string
) {
  const setups = cam.setups;
  const input = setups.createInput(adsk.cam.OperationTypes.AdditiveOperation);
  input.models = models;
  input.name = "AdditiveSetup";

  const camManager = adsk.cam.CAMManager.get();
  if (!camManager) throw Error("No CAM Manager.");
  const libraryManager = camManager.libraryManager;
  const printSettingLibrary = libraryManager.printSettingLibrary;
  const machineLibrary = libraryManager.machineLibrary;
  let machineModel: adsk.cam.Machine | null = null;
  let printSetting: adsk.cam.PrintSetting | null = null;

  let query = machineLibrary.createQuery(
      adsk.cam.LibraryLocations.Fusion360LibraryLocation,
      vendor, model)
  let machines = query.execute()
  // const machines = machineLibrary.childMachines(machineUrl);
  if (!machines) throw Error("No machines found.");

  // Machine model name from Fusion Machine Library
  for (let machine of machines) {
    adsk.log(machine.model)
    if (machine.model == model) {
      machineModel = machine;
      break;
    }
  }
  if (!machineModel) {
    adsk.log(`Machine "${vendor} ${model}" not found`)
    throw "Machine not found"
  }
  adsk.log(`Machine ${machineModel} found`)
  input.machine = machineModel;

  // URL - structure browsing by using Fusion360Library
  const printSettingUrl = printSettingLibrary.urlByLocation(
    adsk.cam.LibraryLocations.Fusion360LibraryLocation,
  );
  const printSettings =
     printSettingLibrary.childPrintSettings(printSettingUrl);
  if (!printSettings) throw Error("No print settings found.");

  // Print Settings name from Fusion PrintSetting Library
  for (let ps of printSettings) {
    // adsk.log(ps.name)
    if (ps.name == printsettingName) {
      printSetting = ps;
      break;
    }
  }
  if (!printSetting) {
    adsk.log(`Printsetting ${printsettingName} not found`)
    throw "Printsetting not found"
  }
  adsk.log(`Printsetting ${printSetting} found`)
  if (printSetting) input.printSetting = printSetting;

  adsk.log("Creating setup now")
  const setup = setups.add(input);

  return setup;
}

// Given an occurence, this finds all child occurences that contain either a B-rep or Mesh body.
// Recursive function to find all occurences at all levels.
function getValidOccurences(
  occurence: adsk.fusion.Occurrence,
): adsk.fusion.Occurrence[] {
  let result: adsk.fusion.Occurrence[] = [];
  const childOcc = occurence.childOccurrences;

  for (let i = 0; i < childOcc.count; ++i) {
    const currentOccurrence = childOcc.item(i);
    if (
      currentOccurrence &&
      currentOccurrence.bRepBodies.count +
        currentOccurrence.component.meshBodies.count >
        0
    ) {
      result.push(currentOccurrence);
    }
    if (currentOccurrence) {
      result = result.concat(getValidOccurences(currentOccurrence));
    }
  }
  return result;
}

function findFile(app: adsk.core.Application,
  hubId: string,
  fileURN: string) : adsk.core.DataFile {

  if (hubId) {
    // Possible hubId formats: base64 encoded string, or business:<id>,
    // or personal:<id> (deprecated)
    const hub =
      app.data.dataHubs.itemById(hubId) ||
      app.data.dataHubs.itemById(`a.${adsk.btoa(`business:${hubId}`, true)}`) ||
      app.data.dataHubs.itemById(`a.${adsk.btoa(`personal:${hubId}`, true)}`);
    if (!hub) throw Error(`Hub with id ${hubId} not found.`);
    adsk.log(`Setting hub: ${hub.name}.`);
    app.data.activeHub = hub;
    adsk.log(`Setting hub: ${hub.name} done`);
  }

  adsk.log(`Finding file`)
  const file = app.data.findFileById(fileURN);
  if (!file) {
    adsk.log(`File not found ${fileURN}.`)
    throw "File not found"
  }
  adsk.log(`Found file "${file.name}"`)
  return file
}


function downloadDataFile(
  app: adsk.core.Application,
  hubId: string,
  fileURN: string,
  fileName: string
){
  let file = findFile(app, hubId, fileURN)
  adsk.log("downloading file")
  let future = file.dataObject
  adsk.log("download started")
  while (future.state == adsk.core.FutureStates.ProcessingFutureState) {
    adsk.log(".")
    wait(1000)
  }
  if (future.state != adsk.core.FutureStates.FinishedFutureState) {
    adsk.log("Download Failed")
    throw "Download Failed";
  }
  let dataObect = future.dataObject
  dataObect.saveToFile(fileName)
  adsk.log("Download successfull")
}

function saveDocument(
  doc: adsk.core.Document,
  saveAsNewDocument: boolean,
  newName: string,
  message: string,
  destinationFolder: adsk.core.DataFolder,
): boolean {
  if (saveAsNewDocument) {
    // let newName = doc.name + " nested";
    adsk.log(`Saving as new document: ${newName}`);
    if (
      doc.saveAs(newName, destinationFolder, message, "")
    ) {
      adsk.log("Document saved successfully.");
      return true;
    } else {
      adsk.log("Document failed to save.");
      return false;
    }
  }

  if (!doc.isModified) {
    adsk.log("Document not modified, not saving.");
    return true;
  }

  adsk.log(`Saving with message: "${message}".`);
  if (doc.save(message)) {
    adsk.log("Document saved successfully.");
    return true;
  } else {
    adsk.log("Document failed to save.");
    return false;
  }
}

function wait(ms: number) {
  const start = new Date().getTime();
  while (new Date().getTime() - start < ms) adsk.doEvents();
}

run();


"""


script_setup_project = """
/**
 * Return default hub and create project "Design Automation for Fusion".
  * @returns {object} {"HubID": string, "HubName": string, "ProjectID": string, "ProjectName": string}
 */

import { adsk } from "@adsk/fas";

function findOrCreateProject(app: adsk.core.Application, projectName: string): adsk.core.DataProject {
  const projects = app.data.activeHub.dataProjects;
  if (!projects) throw Error("Unable to get active hub's projects.");
  for (let i = 0; i < projects.count; ++i) {
    const project = projects.item(i)!;
    if (project.name === projectName) {
      return project
    }
  }
  adsk.log(`Creating new project: ${projectName}`);
  const project = projects.add(projectName);
  if (!project) throw Error("Unable to create new project.");
  return project
}

function run() {
  // Get the Fusion API's application object
  const app = adsk.core.Application.get();
  if (!app) throw Error("No asdk.core.Application.");

  // Log some information
  adsk.log(new Date().toString());
  adsk.log("UserName: " + app.userName);
  adsk.log("User: " + app.currentUser.displayName);
  adsk.log("UserID: " + app.userId);
  adsk.log("Version: " + app.version);
  
  let activeHub = app.data.activeHub;
  if (!activeHub) throw Error("No active hub.");
  adsk.log("HubID: " + activeHub.id);
  adsk.log("HubName: " + activeHub.name);
  let project = findOrCreateProject(app, "Design Automation for Fusion");
  adsk.log("ProjectId: " + project.id);
  adsk.log("ProjectName: " + project.name);
  adsk.log("FolderId: " + project.rootFolder.id);
  adsk.log("FolderName: " + project.rootFolder.name);
  adsk.result = JSON.stringify({"HubID": activeHub.id, "HubName": activeHub.name, "ProjectId": project.id, "ProjectName": project.name, "FolderId": project.rootFolder.id, "FolderName": project.rootFolder.name});
}

run();
"""

def authenticate(CLIENT_ID, CLIENT_SECRET):
    # === CONFIGURATION ===
    REDIRECT_URI = 'http://localhost:8080/'
    SCOPE = 'data:read data:write code:all'
    TOKEN_URL = 'https://developer.api.autodesk.com/authentication/v2/token'
    AUTH_URL = 'https://developer.api.autodesk.com/authentication/v2/authorize'

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        auth_code = None
        def do_GET(self):
            parsed_path = urllib.parse.urlparse(self.path)
            print(f"Received request: {parsed_path.path}")
            if parsed_path.path == '/':
                params = urllib.parse.parse_qs(parsed_path.query)
                if 'code' in params:
                    OAuthHandler.auth_code = params['code'][0]
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b"<html><body><h1>Authorization successful. You may close this window.</h1></body></html>")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Missing code parameter.")
            else:
                self.send_response(404)
                self.end_headers()

    def run_server(server):
        server.handle_request()

    # === Step 1: Start local server to handle 3-legged redirect ===
    server = http.server.HTTPServer(('127.0.0.1', 8080), OAuthHandler)
    thread = threading.Thread(target=run_server, args=(server,))
    thread.start()
    time.sleep(2)  # Give the server a moment to start

    # === Step 2: Request 2-legged token ===
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    two_legged_data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': SCOPE
    }

    request_data = urllib.parse.urlencode(two_legged_data).encode()
    req = urllib.request.Request(TOKEN_URL, data=request_data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            two_legged_token = response_data['access_token']
            print(f"✅ 2-Legged Access Token obtained")
    except urllib.error.HTTPError as e:
        print("❌ Failed to obtain 2-legged token.")
        print(e.read().decode())
        return None

    # === Step 3: Launch browser for user login ===
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Opening browser for Autodesk authentication...")
    webbrowser.open(auth_url)

    thread.join()

    if not OAuthHandler.auth_code:
        print("Authorization code was not received.")
        return None

    # print(f"Authorization code: {OAuthHandler.auth_code}")

    # === Step 4: Exchange code for 3-legged token ===
    three_legged_data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': OAuthHandler.auth_code,
        'redirect_uri': REDIRECT_URI
    }

    request_data = urllib.parse.urlencode(three_legged_data).encode()
    req = urllib.request.Request(TOKEN_URL, data=request_data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            three_legged_token = response_data['access_token']
            print(f"✅ 3-Legged Access Token obtained")
    except urllib.error.HTTPError as e:
        print("❌ Failed to obtain 3-legged token.")
        print(e.read().decode())
        return None

    return {
        "three_legged_token": three_legged_token,
        "two_legged_token": two_legged_token
    }

def nest_parts(file_urn, file_name, quantity, pat, access_token):
    task_parameters = {
        "fileURN": file_urn,
        "fileName": file_name,
        "quantity": quantity,
        "machine": {
            "vendor": "HP",
            "model": "Jet Fusion 4200"
        },
        "printsetting": "HP - MJF"
    }
    workitem_id = submit_workitem("Fusion.ScriptJob+Latest", script, task_parameters, pat, access_token)
    result = observe_workitem(workitem_id, access_token)
    return result["fusionWebURL"]

def prepare_project(pat, access_token):
    workitem_id = submit_workitem("Fusion.ScriptJob+Latest", script_setup_project, {}, pat, access_token)
    result = observe_workitem(workitem_id, access_token)
    return [result["ProjectId"], result["FolderId"]]

def upload_file_to_project(local_file_path, project_id, folder_id, access_token):
    import uuid
    import os
    file_name = "input_" + uuid.uuid4().hex + "_" + os.path.basename(local_file_path)
    
    url = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/storage"

    # === 1. create storage location ===
    headers = {
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/vnd.api+json",
        "Authorization": f"Bearer {access_token}",
        "region": "US"
    }

    data = {
        "jsonapi": { "version": "1.0" },
        "data": {
            "type": "objects",
            "attributes": {
                "name": file_name
            },
            "relationships": {
                "target": {
                    "data": {
                        "type": "folders",
                        "id": folder_id
                    }
                }
            }
        }
    }
    json_data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=json_data, headers=headers, method="POST")
    file_id = None
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            print(f"✅ Created storage location in folder '{folder_id}' of project '{project_id}'.")
            data_id = data['data']['id']
            file_id =  data_id.split("/")[-1]
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to create storage location.")
        return None

    # === 2. Upload the file ===
    url_upload = f"https://developer.api.autodesk.com/oss/v2/buckets/wip.dm.prod/objects/{file_id}/signeds3upload"
    headers = {
        'Authorization': f'Bearer {tokens["three_legged_token"]}',
        'Content-Type': 'application/json',
        "region": "US"
    }

    upload_key = None
    upload_url = None
    req = urllib.request.Request(url_upload, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            print(f"✅ Obtained upload URL")
            upload_key = data['uploadKey']
            upload_url = data['urls'][0]
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to obtain upload URL.")
        return None

    # === 3. Upload the file to S3 ===
    file_data = None
    with open(local_file_path, 'rb') as f:
        file_data = f.read()
    
    req_upload = urllib.request.Request(upload_url, data=file_data, method='PUT')
    try:
        with urllib.request.urlopen(req_upload) as upload_res:
            print("✅ Uploaded local file to OSS")
    except urllib.error.HTTPError as e:
        print("❌ Failed to upload to OSS")
        print(e.read().decode())
        return None
    
    # === 4. Finalize the upload ===
    url_finalize = f"https://developer.api.autodesk.com/oss/v2/buckets/wip.dm.prod/objects/{file_id}/signeds3upload"
    headers = {
        'Authorization': f'Bearer {tokens["three_legged_token"]}',
        'Content-Type': 'application/json',
        "region": "US"
    }
    data = {
        'uploadKey': upload_key
    }
    json_data = json.dumps(data).encode("utf-8")
    req_finalize = urllib.request.Request(url_finalize, data=json_data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req_finalize) as finalize_res:
            data = json.loads(finalize_res.read())
            print("✅ Finalized upload")
    except urllib.error.HTTPError as e:
        print("❌ Failed to finalize upload.")
        print(e.read().decode())
        return False

    # === 5. Create first version ===
    url_create_version = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/items"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/vnd.api+json',
        'Accept': 'application/vnd.api+json'
    }
    data = {
        "jsonapi": { "version": "1.0" },
        "data": {
            "type": "items",
            "attributes": {
                "displayName": file_name,
                "extension": {
                    "type": "items:autodesk.core:File",
                    "version": "1.0"
                }
            },
            "relationships": {
                "tip": {
                    "data": {
                        "type": "versions", "id": "1"
                    }
                },
                "parent": {
                    "data": {
                        "type": "folders",
                        "id": folder_id
                    }
                }
            }
        },
        "included": [{
            "type": "versions",
            "id": "1",
            "attributes": {
                "name": file_name,
                "extension": {
                    "type": "versions:autodesk.core:File",
                    "version": "1.0"
                }
            },
            "relationships": {
                "storage": {
                    "data": {
                        "type": "objects",
                        "id": "urn:adsk.objects:os.object:wip.dm.prod/"+file_id
                    }
                }
            }
        }]
    }
    json_data = json.dumps(data).encode("utf-8")
    req_create_version = urllib.request.Request(url_create_version, data=json_data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req_create_version) as create_res:
            data = json.loads(create_res.read())
            lineage_urn = data["data"]["id"]
            print(f"✅ Created first version of {lineage_urn}")
            return lineage_urn
    except urllib.error.HTTPError as e:
        print("❌ Failed to create first version.")
        print(e.read().decode())
        return False


def upload_file_to_bucket(local_file_path, bucket_key, object_key, access_token):
    # === HEADERS ===
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'region': 'US'
    }

    # === 1. Check if the bucket exists ===
    check_url = f"https://developer.api.autodesk.com/oss/v2/buckets/{bucket_key}/details"
    req = urllib.request.Request(check_url, headers=headers, method='GET')

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            print(f"✅ Bucket '{bucket_key}' already exists.")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"ℹ️ Bucket '{bucket_key}' not found. Creating it...")

            # === 2. Create the bucket ===
            create_url = "https://developer.api.autodesk.com/oss/v2/buckets"
            create_data = {
                "bucketKey": bucket_key,
                "policyKey": "transient"
            }

            create_req = urllib.request.Request(
                create_url,
                data=json.dumps(create_data).encode(),
                headers=headers,
                method='POST'
            )

            try:
                with urllib.request.urlopen(create_req) as create_response:
                    result = json.loads(create_response.read())
                    print(f"✅ Bucket created: {result['bucketKey']}")
            except urllib.error.HTTPError as create_err:
                print("❌ Failed to create bucket.")
                print(create_err.read().decode())
        else:
            print(f"❌ Failed to check bucket. HTTP {e.code}")
            print(e.read().decode())

    # === 3. Upload the file ===
    init_url = f'https://developer.api.autodesk.com/oss/v2/buckets/{bucket_key}/objects/{object_key}/signeds3upload?parts=1'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    req = urllib.request.Request(init_url, headers=headers, method='GET')

    try:
        with urllib.request.urlopen(req) as res:
            init_response = json.loads(res.read().decode())
            upload_key = init_response['uploadKey']
            s3_url = init_response['urls'][0]
            print("✅ Upload URL received from Data Management API")
            # print(s3_url)
    except urllib.error.HTTPError as e:
        print("❌ Failed to initiate upload.")
        print(e.read().decode())
        exit(1)

    # Read your local file
    with open(local_file_path, 'rb') as f:
        file_data = f.read()

    upload_headers = {
        'Content-Length': str(len(file_data)),
        'Content-Type': 'application/octet-stream'
    }

    upload_req = urllib.request.Request(s3_url, data=file_data, headers=upload_headers, method='PUT')

    try:
        with urllib.request.urlopen(upload_req) as upload_res:
            print("✅ Uploaded to S3")
    except urllib.error.HTTPError as e:
        print("❌ S3 upload failed")
        print(e.read().decode())
        exit(1)

    complete_url = f'https://developer.api.autodesk.com/oss/v2/buckets/{bucket_key}/objects/{object_key}/signeds3upload'

    # === Headers ===
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'x-ads-meta-Content-Type': 'application/octet-stream'
    }

    # === Body ===
    data = json.dumps({
        'uploadKey': upload_key
    }).encode('utf-8')

    # === Request ===
    complete_req = urllib.request.Request(complete_url, data=data, headers=headers, method='POST')

    # === Perform the request ===
    try:
        with urllib.request.urlopen(complete_req) as complete_res:
            print("✅ Upload finalized")
            # complete_result = json.loads(complete_res.read().decode())
            # print(json.dumps(complete_result, indent=2))
    except urllib.error.HTTPError as e:
        print("❌ Finalize upload failed")
        print(e.read().decode())
    
    # === Obtain download link ===
    download_url = f'https://developer.api.autodesk.com/oss/v2/buckets/{bucket_key}/objects/{object_key}/signed?access=read'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json;charset=UTF-8'
    }
    data = {
        "minutesExpiration": 10
    }
    download_req = urllib.request.Request(download_url, data=json.dumps(data).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(download_req) as download_res:
            download_response = json.loads(download_res.read().decode())
            print("✅ Obtained download URL")
            # print(download_response['signedUrl'])
            return download_response['signedUrl']
    except urllib.error.HTTPError as e:
        print("❌ Failed to obtain download URL.")
        print(e.read().decode())
    
    return None

def create_activity(access_token, activity_id):
    url = 'https://developer.api.autodesk.com/da/us-east/v3/activities'

    # === HEADERS ===
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
    }

    # === REQUEST BODY ===
    body = {
        "id": activity_id,
        "engine": "Autodesk.Fusion+Latest",
        "commandline": [],
        "parameters": {
            "TaskParameters": {
                "verb": "read",
                "description": "the parameters for the script",
                "required": False
            },
            "PersonalAccessToken": {
                "verb": "read",
                "description": "the personal access token to use",
                "required": True
            },
            "TaskScript": {
                "verb": "read",
                "description": "the script to run",
                "required": True
            },
            "InputFile" :{
                "verb": "get"
            }
        },
        "appbundles": [],
        "settings": {},
        "description": ""
    }

    # === Build request ===
    request_data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=request_data, headers=headers, method='POST')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            print("✅ Activity created successfully:")
            print(json.dumps(response_data, indent=2))
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("ℹ️ Activity already exists.")
        else:
            error_message = e.read().decode()
            print(f"❌ Failed to create activity. HTTP Error {e.code}: ")
            print(error_message)

    # create an alias
     # === HEADERS ===
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
    }

    # === REQUEST BODY ===
    body = {
        "version": 1,
        "id": "Latest",
    }
    url_alias = f'https://developer.api.autodesk.com/da/us-east/v3/activities/{activity_id}/aliases'
    # === Build request ===
    request_data = json.dumps(body).encode()
    req = urllib.request.Request(url_alias, data=request_data, headers=headers, method='POST')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            print("✅ Assigned alias to activity successfully:")
            print(json.dumps(response_data, indent=2))
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("ℹ️ Alias already exists.")
        else:
            error_message = e.read().decode()
            print(f"❌ Failed to assign alias to activity. HTTP Error {e.code}: ")
            print(error_message)

def get_app_nickname(access_token):
    url = 'https://developer.api.autodesk.com/da/us-east/v3/forgeapps/me'
    # === HEADERS ===
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
    }

    # === Build request ===
    req = urllib.request.Request(url, headers=headers, method='GET')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            print("✅ Nickname obtained: "+ json.dumps(response_data, indent=2))
    except urllib.error.HTTPError as e:
        error_message = e.read().decode()
        print(f"❌ Failed to obtain nickname. HTTP Error {e.code}: ")
        print(error_message)
    return response_data

def submit_workitem(qualified_activity_id, task_script, task_parameters, pat, access_token):
    url = 'https://developer.api.autodesk.com/da/us-east/v3/workitems'

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
    }
    body = {
        "activityId": qualified_activity_id,
        "arguments": {
            "PersonalAccessToken": pat,
            "TaskParameters": json.dumps(task_parameters),
            "TaskScript": task_script
        }
    }
    request_data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=request_data, headers=headers, method='POST')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            print("✅ Workitem submitted successfully with ID " + response_data['id'])
            return response_data['id']
    except urllib.error.HTTPError as e:
        error_message = e.read().decode()
        print(f"❌ Failed to submit workitem. HTTP Error {e.code}: ")
        print(error_message)


def submit_packing_workitem(qualified_activity_id, download_link, quantity, pat, access_token):
    url = 'https://developer.api.autodesk.com/da/us-east/v3/workitems'

    # === HEADERS ===
    

    taskParameters = {
        "quantity": quantity,
        "machine": {
            "vendor": "HP",
            "model": "Jet Fusion 4200"
        },
        "printsetting": "HP - MJF",
        "fileName": "input.stp"
    }
    # === REQUEST BODY ===
    body = {
        "activityId": qualified_activity_id,
        "arguments": {
            "PersonalAccessToken": pat,
            "TaskParameters": json.dumps(taskParameters),
            "TaskScript": script, #"import { adsk } from \"@adsk/fas\";\nadsk.log(\"Hello Fusion\");\nadsk.log(adsk.readFileSync(\"input.stp\"));\n",
            # "TaskScript": escaped_script,
            "InputFile": {
                "url": download_link,
                "localName": "input.stp"
            }
        }
    }

    # === Build request ===
    request_data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=request_data, headers=headers, method='POST')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            print("✅ Workitem submitted successfully with ID " + response_data['id'])
            # print(json.dumps(response_data, indent=2))
            return response_data['id']
    except urllib.error.HTTPError as e:
        error_message = e.read().decode()
        print(f"❌ Failed to submit workitem. HTTP Error {e.code}: ")
        print(error_message)

def get_workitem_status(workitem_id, access_token):
    url = f'https://developer.api.autodesk.com/da/us-east/v3/workitems/{workitem_id}'
    # === HEADERS ===
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
    }

    # === Build request ===
    req = urllib.request.Request(url, headers=headers, method='GET')

    # === Send the request ===
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            status = response_data['status']
            report = None
            try:
                report_url = response_data['reportUrl']
                with urllib.request.urlopen(report_url) as report_response:
                    report = json.loads(report_response.read().decode())
            except urllib.error.HTTPError as e:
                error_message = e.read().decode()
                print(f"❌ Failed to obtain report URL. HTTP Error {e.code}: ")
                print(error_message)
            except KeyError:
                pass
            return [status, report]
    except urllib.error.HTTPError as e:
        error_message = e.read().decode()
        print(f"❌ Failed to obtain status. HTTP Error {e.code}: ")
        print(error_message)
    return ["failedInstructions", None]


def print_report(report):
    if not hasattr(print_report, "entries_printed"):
        print_report.entries_printed = 0  # initialize only once
    import datetime
    
    if report and "logs" in report:
        logs = report["logs"]
        if len(logs) > print_report.entries_printed:
            for i in range(print_report.entries_printed, len(logs)):
                # dt = datetime.datetime.fromtimestamp(logs[i]["timestamp"])
                # print(str(dt) + ": ℹ️ " + logs[i]["message"])
                print("📄 " + logs[i]["message"])
        print_report.entries_printed = len(logs)


def observe_workitem(workitem_id, access_token):
    while True:
        [status, report] = get_workitem_status(workitem_id, access_token)
        if status in ["failedDownload", "failedUploadOptional", "failedUpload", "failedLimitProcessingTime", "failedInstructions"]:
            print("❌ Workitem failed with status: " + status)
            print_report(report)
            break
        elif status == 'cancelled':
            print("❌ Workitem cancelled.")
            print_report(report)
            break
        elif status == "pending":
            print("ℹ️ Workitem is pending...")
        elif status == 'inprogress':
            # print("ℹ️ Workitem is in progress...")
            print_report(report)
        if status == 'success':
            print_report(report)
            print("✅ Workitem completed successfully.")
            # print(json.dumps(report["result"], indent=2))
            return json.loads(report["result"])
        time.sleep(1)

if __name__ == "__main__": 
    import sys
    if len(sys.argv) == 4:
        local_file_path = sys.argv[1]
        quantity = int(sys.argv[2])
        credentials_path = sys.argv[3]
    else:
        print("Usage: python cloud_nesting.py file.step quantity credentials.json")
        local_file_path = "Additive MJF.step"
        quantity = 2
        credentials_path = "credentials.json"
    
    # === Load credentials from file ===
    with open(credentials_path, 'r') as f:
        credentials = json.load(f)
        CLIENT_ID = credentials['client_id']
        CLIENT_SECRET = credentials['client_secret']
        PAT = credentials['personal_access_token']

    
    tokens = authenticate(CLIENT_ID, CLIENT_SECRET)
    if not tokens:
        print("❌ Authentication failed.")
        exit(1)
    
    [project_id, folder_id] = prepare_project(PAT, tokens['two_legged_token'])
    file_urn = upload_file_to_project(local_file_path, project_id, folder_id, tokens['three_legged_token'])
    
    import os
    fusion_web_url = nest_parts(file_urn, os.path.basename(local_file_path), quantity, PAT, tokens['two_legged_token'])
    print("✅ Opening nested parts on Fusion Team")
    webbrowser.open(fusion_web_url)

    exit(0)

    # Alternative
    # === Create a bucket and upload file ===
    bucket_name = 'MYNAME'
    bucket_key = f"{CLIENT_ID.lower()}-{bucket_name.lower()}"

    object_key = 'input_file'
    download_link = upload_file_to_bucket(local_file_path, bucket_key, object_key, tokens['two_legged_token'])
    if download_link:
        print(f"✅ File uploaded with object key: {object_key}. Download link generated")

    # === Create activity ===
    ACTIVITY_ID = 'cloud_nesting_3'
    create_activity(tokens['two_legged_token'], activity_id=ACTIVITY_ID)

    # == Submit workitem ===
    PAT = "e14657cf94bd2c2f29ac346b0f3c1a47a57f6b25"
    nickname = get_app_nickname(tokens['two_legged_token'])
    workitem_id = submit_packing_workitem(f'{nickname}.{ACTIVITY_ID}+Latest', download_link, quantity, PAT, tokens['two_legged_token'])

    results = observe_workitem(workitem_id, tokens['two_legged_token'])

    print("✅ Opening nested parts on Fusion Team")
    webbrowser.open(results["fusionWebURL"])
