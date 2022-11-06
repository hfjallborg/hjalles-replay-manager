import datetime
import os
import pathlib
import shutil

import obspython as obs

import psutil

__version__ = "1.0.2"


def script_description():
    return f"<b>Hjalles Replay Manager</b> v. {__version__}" + \
           "<hr>" + \
           "Adds tools to manage your replay buffer files beyond what OBS normally offers, such as" + \
           "<ul>" + \
           "<li>setting a dedicated replay directory, to separate them from regular recordings.</li>" + \
           "<li>keeping a static path to the latest replay, without overwriting previous ones.</li>" + \
           "<li>organizing replay files in a customizable folder structure.</li>" + \
           "</ul>" + \
           "<hr>"


def script_load(settings):
    global SETTINGS

    SETTINGS = {}

    obs.obs_frontend_add_event_callback(on_event)

    output_path = obs.obs_frontend_get_current_record_output_path()
    obs.obs_data_set_default_string(settings, "ReplayOutDir", os.path.join(output_path, "Replays"))
    obs.obs_data_set_default_string(settings, "FilenameFormat", "Replay_%Y-%m-%d_%H-%M-%S")

    # Read OBS config file in AppData dir
    profile_name = obs.obs_frontend_get_current_profile()
    appdata = os.getenv("APPDATA")
    profile_dir = os.path.join(appdata, "obs-studio", "basic", "profiles", profile_name)
    # TODO: FIX PROPER INI READING
    with open(os.path.join(profile_dir, "basic.ini"), "r") as f:
        config_lines = f.read().splitlines()
    for line in config_lines:
        if "RecFilePath" in line:
            path = line.split("=")[1]
        elif "FilenameFormatting" in line:
            format = line.split("=")[1]
        elif "RecFormat" in line:
            file_ext = line.split("=")[1]

    # Generate default persistent replay filename
    file_path = os.path.join(path, f"{format.strip()}.{file_ext}")
    obs.obs_data_set_default_string(settings, "PersistentReplayFilePath", file_path)

    obs.obs_data_set_default_string(settings, "DateSortScheme", "%Y-%m-%d/")
    obs.obs_data_set_default_string(settings, "ExeSortList", ("bf4.exe, Battlefield 4, BF4\n"
                                                              "TslGame.exe, PUBG, PUBG\n"
                                                              "BF2042.exe, Battlefield 2042, BF2042\n"
                                                              "bfv.exe, Battlefield V, BF5"))

    script_update(settings)


def script_update(settings):
    global SETTINGS

    SETTINGS["ReplayOutDir"] = obs.obs_data_get_string(settings, "ReplayOutDir")
    SETTINGS["OverwriteExistingFile"] = obs.obs_data_get_bool(settings, "OverwriteExistingFile")

    SETTINGS["FilenameFormat"] = obs.obs_data_get_string(settings, "FilenameFormat")

    SETTINGS["PersistentReplayFile"] = obs.obs_data_get_bool(settings, "PersistentReplayFile")

    SETTINGS["SortReplays"] = obs.obs_data_get_bool(settings, "SortReplays")
    SETTINGS["SortByDate"] = obs.obs_data_get_bool(settings, "SortByDate")
    SETTINGS["DateSortScheme"] = obs.obs_data_get_string(settings, "DateSortScheme")
    SETTINGS["ReplaySortType"] = obs.obs_data_get_string(settings, "ReplaySortType")
    # Exe sorting
    SETTINGS["ExeSortPrefixes"] = obs.obs_data_get_bool(settings, "ExeSortPrefixes")
    SETTINGS["ExeSortList"] = obs.obs_data_get_string(settings, "ExeSortList")

    if obs.obs_data_get_bool(settings, "PersistentReplayFile"):
        SETTINGS["PersistentReplayFilePath"] = obs.obs_data_get_string(settings, "PersistentReplayFilePath")
    else:
        SETTINGS["PersistentReplayFilePath"] = None


def file_sorting_modified(props, prop, settings, *args, **kwargs):
    value = obs.obs_data_get_string(settings, "ReplaySortType")
    exe_list = obs.obs_properties_get(props, "ExeSortList")
    exe_prefixes = obs.obs_properties_get(props, "ExeSortPrefixes")
    if value == "_sort_by_scene":
        obs.obs_property_set_visible(exe_list, False)
        obs.obs_property_set_visible(exe_prefixes, False)
    elif value == "_sort_by_exe":
        obs.obs_property_set_visible(exe_list, True)
        obs.obs_property_set_visible(exe_prefixes, True)

    return True  # VERY IMPORTANT


def script_properties():
    props = obs.obs_properties_create()

    replay_props = obs.obs_properties_create()
    replay_dir = obs.obs_properties_add_path(replay_props, "ReplayOutDir", "Replay output directory",
                                             obs.OBS_PATH_DIRECTORY, "", "")
    replay_menu = obs.obs_properties_add_group(props, "_replay_menu", "Replay settings", obs.OBS_GROUP_NORMAL,
                                               replay_props)

    filename_props = obs.obs_properties_create()
    info = ('You can use Python strftime tokens to add timestamps to the filename, refer to '
            '<a href="https://strftime.org/">strftime.org</a> for a complete list.')
    obs.obs_properties_add_text(filename_props, "FilenameFormat_info", info, type=obs.OBS_TEXT_INFO)
    filename_format = obs.obs_properties_add_text(filename_props, "FilenameFormat", "Filename format",
                                                  type=obs.OBS_TEXT_DEFAULT)
    overwrite = obs.obs_properties_add_bool(filename_props, "OverwriteExistingFile", "Overwrite if file exists")
    filename_format_menu = obs.obs_properties_add_group(props, "_filename_format_menu",
                                                        "Filename formatting (replays only)",
                                                        obs.OBS_GROUP_NORMAL, filename_props)

    persistant_file_props = obs.obs_properties_create()
    info = ("Use this if you need a static path to the latest replay file, e.g. for an instant replay script. "
            "This will be overwritten every time you save the replay buffer.")
    obs.obs_properties_add_text(persistant_file_props, "PersistentReplayFilePath_info", info, type=obs.OBS_TEXT_INFO)
    persistant_filepath = obs.obs_properties_add_path(persistant_file_props, "PersistentReplayFilePath",
                                                      "File path", obs.OBS_PATH_FILE_SAVE, "", "")
    persistant_file_menu = obs.obs_properties_add_group(props, "PersistentReplayFile", "Persistent replay file",
                                                        obs.OBS_GROUP_CHECKABLE, persistant_file_props)

    # ===== FILE SORTING OPTIONS =====
    file_sorting_props = obs.obs_properties_create()

    sort_by_date = obs.obs_properties_add_bool(file_sorting_props, "SortByDate", "Sort files by date")
    date_sort_scheme = obs.obs_properties_add_text(file_sorting_props, "DateSortScheme", "Date sorting scheme",
                                                   type=obs.OBS_TEXT_DEFAULT)
    obs.obs_property_set_enabled(date_sort_scheme, False)

    file_sort_by = obs.obs_properties_add_list(file_sorting_props, "ReplaySortType", "Categorize replays by",
                                               type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(file_sort_by, file_sorting_modified)
    obs.obs_property_list_add_string(file_sort_by, "Executable", "_sort_by_exe")
    obs.obs_property_list_add_string(file_sort_by, "Active scene", "_sort_by_scene")

    exe_prefixes = obs.obs_properties_add_bool(file_sorting_props, "ExeSortPrefixes",
                                               "Add per executable prefix to filename")
    exe_list = obs.obs_properties_add_text(file_sorting_props, "ExeSortList", "Executable list",
                                           type=obs.OBS_TEXT_MULTILINE)
    file_sorting_menu = obs.obs_properties_add_group(props, "SortReplays", "Automatic file labeling and sorting",
                                                     obs.OBS_GROUP_CHECKABLE, file_sorting_props)

    return props


def getListOfProcessSortedByMemory():
    '''
    Get list of running process sorted by Memory Usage
    '''
    listOfProcObjects = []
    # Iterate over the list
    for proc in psutil.process_iter():
        try:
            # Fetch process details as dict
            pinfo = proc.as_dict(attrs=['pid', 'name', 'username'])
            pinfo['vms'] = proc.memory_info().vms / (1024 * 1024)
            # Append dict to list
            listOfProcObjects.append(pinfo);
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    # Sort list of dict by key vms i.e. memory usage
    listOfProcObjects = sorted(listOfProcObjects, key=lambda procObj: procObj['vms'], reverse=True)
    return listOfProcObjects


def get_latest_replay_path():
    # Code copied from https://obsproject.com/forum/resources/instant-replay-vlc.621/

    replay_buffer = obs.obs_frontend_get_replay_buffer_output()
    cd = obs.calldata_create()
    ph = obs.obs_output_get_proc_handler(replay_buffer)
    obs.proc_handler_call(ph, "get_last_replay", cd)
    path = obs.calldata_string(cd, "path")
    obs.calldata_destroy(cd)
    obs.obs_output_release(replay_buffer)

    return path


def find_exe_from_list():
    global SETTINGS
    exe_list = SETTINGS["ExeSortList"]
    # Parse executable list into dict
    games = {}
    for game_list in [game.split(",") for game in exe_list.strip().splitlines()]:
        games[game_list[0]] = {"name": game_list[1], "prefix": game_list[2]}
    for exe in getListOfProcessSortedByMemory():
        if exe["name"] in games:
            return games[exe["name"]]
    return None


def generate_filename(prefix="", suffix="", file_ext=""):
    global SETTINGS
    file_ext = file_ext.replace(".", "")
    filename = datetime.datetime.now().strftime(SETTINGS["FilenameFormat"])
    if prefix is not "":
        filename = f"{prefix}_{filename}"
    if suffix is not "":
        filename = f"{filename}_{suffix}"
    if file_ext is not "":
        filename = f"{filename}.{file_ext}"
    return filename


def generate_dir(root_dir):
    global SETTINGS
    return_dir = root_dir
    if SETTINGS["SortReplays"]:
        if SETTINGS["ReplaySortType"] == "_sort_by_scene":
            current_scene = obs.obs_frontend_get_current_scene()
            name = obs.obs_source_get_name(current_scene)
            return_dir = os.path.join(return_dir, f"{name}/")
        elif SETTINGS["ReplaySortType"] == "_sort_by_exe":
            active_exe = find_exe_from_list()
            if active_exe is not None:
                name = active_exe["name"]
                return_dir = os.path.join(return_dir, name)
        if SETTINGS["SortByDate"]:
            date_path = datetime.datetime.now().strftime(SETTINGS["DateSortScheme"])
            return_dir = os.path.join(return_dir, date_path)
    return return_dir


def on_event(event):
    global SETTINGS

    if event == obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
        replay_path = get_latest_replay_path()

        file_ext = pathlib.Path(replay_path).suffix
        filename = pathlib.Path(replay_path)
        if len(filename.name.split(".")[0]) == 0:  # Empty filename, e.g. ".mp4"
            file_ext = filename.name.split(".")[1]
        prefix = ""
        if SETTINGS["ExeSortPrefixes"]:
            active_exe = find_exe_from_list()
            if active_exe is not None:
                prefix = active_exe["prefix"]
        new_filename = generate_filename(prefix=prefix, file_ext=file_ext)
        save_dir = generate_dir(SETTINGS["ReplayOutDir"])
        pathlib.Path(save_dir).mkdir(parents=True, exist_ok=True)
        new_path = os.path.join(save_dir, new_filename)
        # Generate unique filename by appending e.g. "_1"
        if not SETTINGS["OverwriteExistingFile"]:
            num = 1
            while os.path.exists(new_path):
                filename = pathlib.Path(new_path).stem
                file_ext = pathlib.Path(new_path).suffix
                test_filename = f"{filename}_{num}{file_ext}"
                test_path = os.path.join(save_dir, test_filename)
                if not os.path.exists(test_path):
                    new_path = test_path
                    break
                num += 1
        shutil.move(replay_path, new_path)
        if SETTINGS["PersistentReplayFilePath"] is not None:
            try:
                shutil.copyfile(new_path, SETTINGS["PersistentReplayFilePath"])
            except shutil.SameFileError:
                pass
