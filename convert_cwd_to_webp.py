import os
import shutil
from os import listdir
from os.path import isfile, join
from subprocess import Popen, TimeoutExpired, DEVNULL, STDOUT, PIPE
from threading import Thread, current_thread
from sys import stdout, argv
from time import localtime, sleep
from queue import SimpleQueue, Empty

USAGE_TEXT = """\
Usage:
    py ConvertHereToWebp [-t <NUM_THREADS>] [-s|--single <IMAGE> [OPTIONS]
    py ConvertHereToWebp --mdtest <IMAGE> [OPTIONS]
    py ConvertHereToWebp --list [OPTIONS]

Input Types Supported: PNG TIFF TGA WEBP
    
OPTIONS:
    -t <NUM_THREADS> - Set number of threads to do
    -s (--single) - compress only provided image and exit
    --no-ignore-webp - convert all types but webp into webps
    --list - lists all files to be converted and quit
    --list-md - same as --list but checks for extra metadata
    --mdtest <IMAGE> - Tests if provided image has extra metadata
    --(no-)force-metadata - Forces metadata to be transferred (or not to be), skipping check
    --remove-original - removes original image and moves converted image into place (only applicable for -s)
    --nolog - doesn't make log files\n"""

DEFAULT_TAGS = ['ExifTool Version Number',
                'File Name',
                'Directory',
                'File Size',
                'File Modification Date/Time',
                'File Access Date/Time',
                'File Creation Date/Time',
                'File Permissions',
                'File Type',
                'File Type Extension',
                'MIME Type',
                'Image Width',
                'Image Height',
                'Bit Depth',
                'Color Type',
                'Compression',
                'Filter',
                'Interlace',
                'Image Size',
                'Megapixels']

def MakeDir(dirname: str) -> None:
    try:
        os.mkdir(dirname)
    except FileExistsError:
        pass
    except OSError:
        stdout.write(f"\n{dirname} could not be created! Check you have permissions to modify this directory\n")
        exit()
    except:
        stdout.write(f"An uncaught exeption occurred when making {dirname} directory!\n")
        exit()

def InitLogSystem() -> None:
    global LOG_TO_STDOUT
    global LOGGING_DIR
    LOGGING_DIR = f"WebpLogs{os.sep}{localtime().tm_mon}-{localtime().tm_mday}_{localtime().tm_hour}-{localtime().tm_min}-{localtime().tm_sec}"
    root = os.getcwd()
    try:
        for dir in LOGGING_DIR.split(os.sep):
            try:
                os.mkdir(dir)
            except FileExistsError:
                pass
            os.chdir(dir)
        LOG_TO_STDOUT = False
        stdout.write("Log system initialized successfully\n")
    except OSError:
        stdout.write(f"\nLog folder could not be created, will be logging to stdout\n")
        LOG_TO_STDOUT = True
    finally:
        os.chdir(root)

def WriteLog(logLevel: int, file: str) -> None:
    # Loglevel is like an enum
    # 0 - starting convert
    # 1 - starting exif transfer out
    # 2 - starting exif transfer in
    # 3 - operation finished
    # 4 - operation failed
    if LOGGING_DIR == "": return
    if LOG_TO_STDOUT:
        return LogToSTDOut(logLevel, file)
    else:
        return LogToFile(logLevel, file)

def LogToFile(logLevel: int, file: str) -> None:
    with open(f"{LOGGING_DIR}{os.sep}{current_thread().name}.log", "a") as logfile:
        if logLevel == 0:
            logfile.write(f"Converting {file}...")
        elif logLevel == 1:
            logfile.write("Getting EXIF data...")
        elif logLevel == 2:
            logfile.write("Merging EXIF data...")
        elif logLevel == 3:
            logfile.write("FINISHED\n")
        elif logLevel == 4:
            logfile.write("FAILED\n")

def LogToSTDOut(logLevel: int, file: str) -> None:
    global G_logQueue
    if logLevel == 0:
        G_logQueue.put(f"Converting {file}...")
    elif logLevel == 1:
        G_logQueue.put(f"Getting EXIF data from {file}...")
    elif logLevel == 2:
        G_logQueue.put(f"Merging EXIF data to {file[:-4:]}.webp...")
    elif logLevel == 3:
        G_logQueue.put(f"FINISHED {file}")
    elif logLevel == 4:
        G_logQueue.put(f"FAILED WORK ON {file}")

def LogTail():
    global LOG_TO_STDOUT
    global G_logQueue
    global NUM_THREADS
    global G_threadsDone
    if not LOG_TO_STDOUT: return
    
    while G_threadsDone != NUM_THREADS:
        try:
            stdout.write(f"{G_logQueue.get(block=True, timeout=0.1)}\n")
        except Empty:
            sleep(0.1)

def PrintImageData(imgList: list, checkMD: bool) -> None:
    for img in imgList:
        stdout.write(f"\t{img}")
        if (checkMD) and CheckIfMetadata(img):
            stdout.write(" + Extra Data")
        stdout.write("\n")

def RunShell_sync(args: list[str]) -> int:
    ret = Popen(args, stdout=DEVNULL, stderr=STDOUT)
    ret.wait()
    return ret.returncode

def CheckIfMetadata(filename: str) -> bool:
    if G_forceMD != None:
        return G_forceMD
    proc = Popen([shutil.which("exiftool"), filename], stdout=PIPE)
    try:
        output = proc.communicate(timeout=5)[0]
    except TimeoutExpired:
        WriteError(3, filename)
        return False
    
    global DEFAULT_TAGS
    for line in output.decode('utf-8').split(os.linesep):
        isDefault = False
        for tag in DEFAULT_TAGS:
            if (line.startswith(tag)):
                isDefault = True
                break
        if not isDefault and line != '':
            return True
    return False

def MetadataCheck(filename: str) -> str:
    proc = Popen([shutil.which("exiftool"), filename], stdout=PIPE)
    output = proc.communicate(timeout=3)[0]
    
    global DEFAULT_TAGS

    for line in output.decode('utf-8').split(os.linesep):
        isDefault = False
        for tag in DEFAULT_TAGS:
            if (line.startswith(tag)):
                isDefault = True
                stdout.write(f"DEFAULT: {line}\n")
                break
        if not isDefault and line != '':
            stdout.write(f"NOT DEFAULT: {line}\n")

def ConversionWorker(images: list):
    global G_threadsDone
    for inFile in images:
        ConvertSingleImage(inFile)
    G_threadsDone += 1

def ConvertSingleImage(image: str) -> str: 
    global G_imagesDone
    outFile = "WebPs" + os.sep + GetFilename(image) + ".webp"
    
    # Convert image
    WriteLog(0, image)
    ret = RunShell_sync([shutil.which("cwebp"), "-lossless", "-metadata", "icc", "-mt", "-z", "9", "-alpha_filter", "best", "-progress", "-exact", image, "-o", outFile])
    if ret != 0:
        WriteLog(4, image)
        WriteError(0, image)
        return ""
    WriteLog(3, image)
    
    if CheckIfMetadata(image):
        TransferMetadata(image, outFile)
    G_imagesDone += 1
    return outFile

def TransferMetadata(image: str, outFile: str):
    xmpFile = "xmpdata_tmp" + os.sep + GetFilename(image) + ".xmp"
    
    # transferring old EXIF data to tmp XMP file
    WriteLog(1, image)
    ret = RunShell_sync([shutil.which("exiftool"), "-u", "-U", "-P", "-a", "-z", "-tagsFromFile", image, xmpFile])
    if ret != 0:
        WriteLog(4, image)
        WriteError(1, image)
        return outFile
    WriteLog(3, image)
    
    # transferring tmp XMP data back to converted image
    WriteLog(2, image)
    ret = RunShell_sync([shutil.which("webpmux"), "-set", "xmp", xmpFile, outFile, "-o", outFile])
    if ret != 0:
        WriteLog(4, image)
        WriteError(2, image)
        return outFile
    WriteLog(3, image)

def CollectFiles(directory: str, extensions: tuple[str]) -> list[str]:
    filenameList = [file for file in listdir(directory) if isfile(join(directory, file)) and (file.endswith(extensions))]
    
    if directory != ".":
        for i in range(len(filenameList)):        
            filenameList[i] = directory + os.sep + filenameList[i]
    
    return filenameList

def ProcessCmdOptions():
    global G_forceMD
    global G_collectFormats
    global NUM_THREADS
    
    if ("--help" in argv) or ("-h" in argv):
        stdout.write(USAGE_TEXT)
        exit()

    if "--force-metadata" in argv:
        G_forceMD = True
    if "--no-force-metadata" in argv:
        G_forceMD = False
    
    if "--mdtest" in argv:
        MetadataCheck(argv[2])
        exit()
    
    if "--no-ignore-webp" in argv:
        G_collectFormats = ("png", "tiff", "tif", "tga", "webp")
    
    # Options that take in arguments
    for i in range(len(argv)):
        if argv[i] == "-t":
            try:
                NUM_THREADS = int(argv[i+1])
            except ValueError:
                stdout.write(f'"{argv[2]}" is not an integer!\n')
                stdout.write(USAGE_TEXT)
                exit()
        if argv[i] == "-d":
            try:
                os.chdir(argv[i+1])
            except OSError:
                uinput = input("Could not enter/find directory, proceed in cwd? (y/n): ").casefold()
                if uinput in ("y", "yes"):
                    continue
                elif uinput in ("n", "no"):
                    exit()
                else: exit()
    
    if NUM_THREADS == 0:
        NUM_THREADS = 6

def GetFilename(file: str) -> str:
    if file[-4::] in ("webp", "tiff"):
        extLength = -5
    else:
        extLength = -4
    
    if not os.sep in file: return file[:extLength:]
    else: return file.split(os.sep)[len(file.split(os.sep))-1][:extLength:]

def WriteError(issueType: int, image: str):
    # issueType: enum
    # 0 - file conversion error
    # 1 - metadata extraction error
    # 2 - metadata insertion error
    # 3 - metadata detection error
    global LOGGING_DIR
    with open(f"{LOGGING_DIR}{os.sep}ErrorFiles.txt", "at") as errorLog:
        if issueType == 0:
            errorLog.write(f"{image} CONVERSION ERROR\n")
        elif issueType == 1:
            errorLog.write(f"{image} METADATA EXTRACTION ERROR\n")
        elif issueType == 2:
            errorLog.write(f"{image} METADATA INSERTIONS ERROR\n")
        elif issueType == 3:
            errorLog.write(f"{image} METADATA DETECTION ERROR\n")

NUM_THREADS = 0

# Controls the method that logging functions use to log behavior
# 0 - log to files
# 1 - log to stdout
LOG_TO_STDOUT = False
LOGGING_DIR = ""
G_logQueue = SimpleQueue()
G_forceMD = None
G_collectFormats = ("png", "tiff", "tif", "tga")
G_imagesDone = 0
G_threadsDone = 0

if __name__ == '__main__':
    
    ProcessCmdOptions()
    
    srcImages = CollectFiles(".", G_collectFormats)
    
    if "--list-md" in argv:
        PrintImageData(srcImages, True)
        exit()

    if "--list" in argv:
        PrintImageData(srcImages, False)
        exit()
    
    if not "--nolog" in argv:
        InitLogSystem()

    if ("--single" in argv) or ("-s" in argv):
        for i in range(len(argv)):
            if argv[i] in ("--single", "-s"):
                argument = i + 1
        if os.path.dirname(argv[argument]) != '':
            os.chdir(os.path.dirname(argv[argument]))
        
        filePath = argv[argument].split(os.sep)
        filename = filePath[len(filePath)-1]
        MakeDir('WebPs')
        MakeDir('xmpdata_tmp')
        outFile = ConvertSingleImage(filename)
        shutil.rmtree('xmpdata_tmp')
        shutil.copy2(outFile, ".")
        
        if "--remove-original" in argv:
            os.remove(argv[argument])

        if len(listdir('WebPs')) <= 1:
            shutil.rmtree('WebPs')
        exit()

    # Recovery Part I - failed images
    if "--recover" in argv:
        dstImages = CollectFiles("WebPs", ("webp"))
        
        for i in range(len(dstImages)):
            dstImages[i] = GetFilename(dstImages[i])
        
        toRemove = []
        
        for i in range(len(srcImages)):
            
            if GetFilename(srcImages[i]) in dstImages:
                toRemove.append(srcImages[i])
        
        for img in toRemove:
            try:
                srcImages.remove(img)
            except ValueError: pass
        
        if len(srcImages) == 0:
            stdout.write("All images converted successfully.\n")
        else:
            stdout.write(f"Found {len(srcImages)} images that failed to convert\n")
    else:
        if len(srcImages) == 0:
            stdout.write("No images found in cwd.\n")
            exit()
        stdout.write(f"Found {len(srcImages)} images in cwd\n")


    threadImages = []
    for i in range(NUM_THREADS):
        threadImages.append([])

    for i in range(len(srcImages)):
        threadImages[i % NUM_THREADS].append(srcImages[i])
        
    MakeDir('WebPs')
    MakeDir('xmpdata_tmp')

    threadPool = [Thread(target=ConversionWorker, args=[threadImages[i]], name=f'Thread{i}') for i in range(NUM_THREADS)]

    for thread in threadPool:
        thread.start()
    
    LogTail()
    
    while G_threadsDone != NUM_THREADS:
        stdout.write(f"\x1b[1K\rConverting Image ({G_imagesDone}/{len(srcImages)})")
        sleep(0.1)
    stdout.write(f"\x1b[1K\rConverting Image ({len(srcImages)}/{len(srcImages)})\n")
        

    for thread in threadPool:
        thread.join()
    
    # Recovery Part II - metadata
    if "--recover" in argv:
        outFiles = CollectFiles("WebPs", ("webp"))
        fuckedMD = []
        G_imagesDone = 0
        for dstImg in outFiles:
            G_imagesDone += 1
            stdout.write(f"\x1b[1K\r Checking image metadata... ({G_imagesDone}/{len(outFiles)})")
            if not CheckIfMetadata(dstImg):
                fuckedMD.append(dstImg)
        
        if len(fuckedMD) != 0:
            stdout.write("\nThere is no metadata to recover.")
            shutil.rmtree('xmpdata_tmp')
            exit()
        
        if "--no-ignore-webp" in argv:
            srcFiles = CollectFiles(".", ("png", "webp", "tiff", "tif", "tga"))
        else:
            srcFiles = CollectFiles(".", ("png", "tiff", "tif", "tga"))
        
        G_imagesDone = 0
        for img in fuckedMD:
            for i in range(len(srcFiles)):
                G_imagesDone += 1
                stdout.write(f"\x1b[1K\r Checking image metadata... ({G_imagesDone}/{len(fuckedMD)})")
                if GetFilename(img) != GetFilename(srcFiles[i]): continue
                if not CheckIfMetadata(srcFiles[i]):
                    fuckedMD.remove(img)
        
        if len(fuckedMD) == 0:
            stdout.write("\nThere is no metadata to recover.")
            shutil.rmtree('xmpdata_tmp')
            exit()
        
        doneCount = 0
        for outImage in fuckedMD:
            for i in range(len(srcFiles)):
                if GetFilename(outImage) != GetFilename(srcFiles[i]): continue
                inImage = srcFiles[i]
            doneCount += 1
            stdout.write(f"\x1b[1K\rTransferring metadata...({doneCount}/{len(fuckedMD)})")
            TransferMetadata(inImage, outImage)

    shutil.rmtree('xmpdata_tmp')