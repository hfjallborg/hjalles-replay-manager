import datetime
import os
import pathlib
import shutil
import threading
import subprocess
import glob

import obspython as obs

import psutil

__version__ = "1.1.0-alpha.1"

CURRENT_BUFFER = {
    "start_time": None,
    "saved_replays": []
}


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
    global SETTINGS, CURRENT_BUFFER

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

    obs.obs_data_set_default_string(settings, "DatetimeSortScheme", "%Y-%m-%d/")
    obs.obs_data_set_default_string(settings, "ExeSortList", ("bf4.exe, Battlefield 4, BF4\n"
                                                              "TslGame.exe, PUBG, PUBG\n"
                                                              "BF2042.exe, Battlefield 2042, BF2042\n"
                                                              "bfv.exe, Battlefield V, BF5"))

    script_update(settings)


def script_update(settings):
    global SETTINGS, SCRIPT_PROPERTIES

    SCRIPT_PROPERTIES = settings

    SETTINGS["ReplayOutDir"] = obs.obs_data_get_string(settings, "ReplayOutDir")
    SETTINGS["OverwriteExistingFile"] = obs.obs_data_get_bool(settings, "OverwriteExistingFile")

    SETTINGS["FilenameFormat"] = obs.obs_data_get_string(settings, "FilenameFormat")

    SETTINGS["PersistentReplayFile"] = obs.obs_data_get_bool(settings, "PersistentReplayFile")

    SETTINGS["SortReplays"] = obs.obs_data_get_bool(settings, "SortReplays")
    SETTINGS["SortByDate"] = obs.obs_data_get_bool(settings, "SortByDate")
    SETTINGS["DatetimeSortScheme"] = obs.obs_data_get_string(settings, "DatetimeSortScheme")
    SETTINGS["DatetimeSortBase"] = obs.obs_data_get_string(settings, "DatetimeSortBase")

    SETTINGS["ReplaySortType"] = obs.obs_data_get_string(settings, "ReplaySortType")
    # Exe sorting
    SETTINGS["ExeSortPrefixes"] = obs.obs_data_get_bool(settings, "ExeSortPrefixes")
    SETTINGS["ExeSortList"] = obs.obs_data_get_string(settings, "ExeSortList")

    SETTINGS["RemuxReplays"] = obs.obs_data_get_bool(settings, "RemuxReplays")
    SETTINGS["RemuxMode"] = obs.obs_data_get_string(settings, "RemuxMode")
    SETTINGS["RemuxFilenameFormat"] = obs.obs_data_get_string(settings, "RemuxFilenameFormat")
    SETTINGS["RemuxVEncoder"] = obs.obs_data_get_string(settings, "RemuxVEncoder")
    SETTINGS["RemuxCRF"] = obs.obs_data_get_int(settings, "RemuxCRF")
    SETTINGS["RemuxFileContainer"] = obs.obs_data_get_string(settings, "RemuxFileContainer")
    SETTINGS["RemuxBitrate"] = obs.obs_data_get_int(settings, "RemuxBitrate")
    SETTINGS["RemuxBitrateMode"] = obs.obs_data_get_string(settings, "RemuxBitrateMode")
    SETTINGS["RemuxCustomFFmpeg"] = obs.obs_data_get_string(settings, "RemuxCustomFFmpeg")
    SETTINGS["RemuxH264Preset"] = obs.obs_data_get_string(settings, "RemuxH264Preset")
    SETTINGS["ManualRemuxMode"] = obs.obs_data_get_string(settings, "ManualRemuxMode")
    SETTINGS["ManualRemuxInputFile"] = obs.obs_data_get_string(settings, "ManualRemuxInputFile")
    SETTINGS["ManualRemuxInputFolder"] = obs.obs_data_get_string(settings, "ManualRemuxInputFolder")

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

    datetime_sort = obs.obs_data_get_bool(settings, "SortByDate")
    datetime_sort_base = obs.obs_properties_get(props, "DatetimeSortBase")
    datetime_sort_scheme = obs.obs_properties_get(props, "DatetimeSortScheme")
    if datetime_sort:
        obs.obs_property_set_visible(datetime_sort_base, True)
        obs.obs_property_set_visible(datetime_sort_scheme, True)
    else:
        obs.obs_property_set_visible(datetime_sort_base, False)
        obs.obs_property_set_visible(datetime_sort_scheme, False)


    return True  # VERY IMPORTANT


def remux_settings_modified(props, prop, settings, *args, **kwargs):
    remux_file_format = obs.obs_properties_get(props, "RemuxFilenameFormat")
    if obs.obs_data_get_bool(settings, "RemuxReplaceOriginal"):
        obs.obs_property_set_enabled(remux_file_format, False)
    else:
        obs.obs_property_set_enabled(remux_file_format, True)

    # Get all UI elements for remux settings

    overwrite_b = obs.obs_properties_get(props, "RemuxReplaceOriginal")
    v_encoder_s = obs.obs_properties_get(props, "RemuxVEncoder")
    container_prop = obs.obs_properties_get(props, "RemuxFileContainer")
    br_slider = obs.obs_properties_get(props, "RemuxBitrate")
    crf_slider = obs.obs_properties_get(props, "RemuxCRF")
    preset_selector = obs.obs_properties_get(props, "RemuxH264Preset")
    filename_format = obs.obs_properties_get(props, "RemuxFilenameFormat")
    custom_ffmpeg = obs.obs_properties_get(props, "RemuxCustomFFmpeg")
    bitrate_mode = obs.obs_properties_get(props, "RemuxBitrateMode")

    remux_mode = obs.obs_data_get_string(settings, "RemuxMode")
    v_encoder = obs.obs_data_get_string(settings, "RemuxVEncoder")
    h264_preset = obs.obs_data_get_string(settings, "RemuxH264Preset")
    containers = []

    # Visble properties in standard mode
    std_props = [overwrite_b, v_encoder_s, container_prop, br_slider, crf_slider, preset_selector, filename_format,
                 bitrate_mode]
    # Visible properties in custom ffmpeg mode
    custom_props = [custom_ffmpeg, filename_format, overwrite_b]

    obs.obs_property_list_clear(container_prop)
    obs.obs_property_list_clear(preset_selector)
    if remux_mode == "standard":
        for p in custom_props:
            obs.obs_property_set_visible(p, False)
        for p in std_props:
            obs.obs_property_set_visible(p, True)

        if v_encoder == "copy":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            copy_props = [container_prop, v_encoder_s, filename_format, overwrite_b]
            for prop in copy_props:
                obs.obs_property_set_visible(prop, True)
            for prop in std_props:
                if prop not in copy_props:
                    obs.obs_property_set_visible(prop, False)

        elif v_encoder == "libx264":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            libx264_props = [overwrite_b, v_encoder_s, filename_format, container_prop, crf_slider, preset_selector]
            for p in libx264_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in libx264_props:
                    obs.obs_property_set_visible(p, False)
            for preset in ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower",
                           "veryslow", "placebo"]:
                obs.obs_property_list_add_string(preset_selector, preset, preset)

        elif v_encoder == "h264_nvenc":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            h264nvenc_props = [overwrite_b, v_encoder_s, filename_format, container_prop, br_slider, preset_selector]
            for p in h264nvenc_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in h264nvenc_props:
                    obs.obs_property_set_visible(p, False)
            for preset in [("default", 0), ("slow", 1), ("medium", 2), ("fast", 3), ("hp", 4), ("hq", 5), ("bd", 6),
                           ("ll", 7), ("llhq", 8), ("llhp", 9), ("lossless", 10), ("losslesshp", 11)]:
                obs.obs_property_list_add_string(preset_selector, preset[0], str(preset[1]))

        elif v_encoder == "libsvtav1":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            libaom_props = [overwrite_b, v_encoder_s, bitrate_mode, filename_format, container_prop]
            for p in libaom_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in libaom_props:
                    obs.obs_property_set_visible(p, False)

            obs.obs_property_list_clear(bitrate_mode)
            obs.obs_property_list_add_string(bitrate_mode, "Constant quality", "cq")
            br_mode = obs.obs_data_get_string(settings, "RemuxBitrateMode")
            if br_mode == "cq":
                obs.obs_property_set_visible(br_slider, False)
                obs.obs_property_set_visible(crf_slider, True)

        # elif v_encoder == "h264_amf":
        #     amf_props = [overwrite_b, v_encoder_s, filename_format, br_slider, container_prop]
        #     for prop in amf_props:
        #         obs.obs_property_set_visible(prop, True)
        #     for prop in std_props:
        #         if prop not in amf_props:
        #             obs.obs_property_set_visible(prop, False)
        #     containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
        for c in containers:
            obs.obs_property_list_add_string(container_prop, c[1], c[0])

    elif remux_mode == "custom_ffmpeg":
        for p in std_props:
            obs.obs_property_set_visible(p, False)
        for p in custom_props:
            obs.obs_property_set_visible(p, True)

    manual_remux_mode = obs.obs_data_get_string(settings, "ManualRemuxMode")
    manual_remux_file = obs.obs_properties_get(props, "ManualRemuxInputFile")
    manual_remux_folder = obs.obs_properties_get(props, "ManualRemuxInputFolder")
    if manual_remux_mode == "file":
        obs.obs_property_set_visible(manual_remux_file, True)
        obs.obs_property_set_visible(manual_remux_folder, False)
    elif manual_remux_mode == "batch":
        obs.obs_property_set_visible(manual_remux_file, False)
        obs.obs_property_set_visible(manual_remux_folder, True)

    return True


def generate_ffmpeg_cmd(input_path):
    global SETTINGS

    input_file = pathlib.Path(input_path)
    filename_format = SETTINGS["RemuxFilenameFormat"]
    stem = filename_format.replace("%FILE%", input_file.stem)
    container = SETTINGS["RemuxFileContainer"]
    output_filename = f"{stem}.{container}"
    output_path = os.path.join(input_file.parent, output_filename)

    if SETTINGS["RemuxMode"] == "standard":
        v_encoder = SETTINGS["RemuxVEncoder"]

        if v_encoder == "copy":
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v copy -c:a copy -map 0 {output_path}"

        elif v_encoder == "libx264":
            crf = SETTINGS["RemuxCRF"]
            preset = SETTINGS["RemuxH264Preset"]
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v {v_encoder} -preset 0 -crf {crf} -c:a copy -map 0 {output_path}"

        elif v_encoder == "h264_nvenc":
            cbr = SETTINGS["RemuxBitrate"]
            preset = SETTINGS["RemuxH264Preset"]
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v h264_nvenc -preset {preset} -b:v {cbr}M -c:a copy -map 0 {output_path}"

        elif v_encoder == "libsvtav1":
            if SETTINGS["RemuxBitrateMode"] == "cq":
                cq = SETTINGS["RemuxCRF"]
                ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v {v_encoder} -crf {cq} -b:v 0 -c:a copy -map 0 {output_path}"

        # elif v_encoder == "h264_amf":
        #     cbr = int(SETTINGS["RemuxBitrate"]) * 1000
    elif SETTINGS["RemuxMode"] == "custom_ffmpeg":
        ffmpeg_cmd = SETTINGS["RemuxCustomFFmpeg"].replace("%INPUT%", input_path).replace("%OUTPUT%", stem)

    return ffmpeg_cmd


def run_ffmpeg(ffmpeg_cmd):
    p = subprocess.run(ffmpeg_cmd, shell=True)
    return


def manual_remux(props, prop, *args, **kwargs):
    if SETTINGS["ManualRemuxMode"] == "file":
        ffmpeg_input = SETTINGS["ManualRemuxInputFile"]
        ffmpeg_cmd = generate_ffmpeg_cmd(ffmpeg_input)
        remux_thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,), daemon=True)
        remux_thread.start()
    elif SETTINGS["ManualRemuxMode"] == "batch":
        input_folder = SETTINGS["ManualRemuxInputFolder"]
        file_formats = ["mp4", "mkv"]
        input_files = []
        for ff in file_formats:
            input_files += glob.glob(f"{input_folder}/*.{ff}")
        remux_threads = []
        for file in input_files:
            ffmpeg_cmd = generate_ffmpeg_cmd(file)
            thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,))
            remux_threads.append(thread)
        for thread in remux_threads:
            thread.start()


def remux_properties(props):
    auto_remux_props = obs.obs_properties_create()
    replace_orig = obs.obs_properties_add_bool(auto_remux_props, "RemuxReplaceOriginal", "Overwrite original file")
    remux_filename = obs.obs_properties_add_text(auto_remux_props, "RemuxFilenameFormat",
                                                 "Remuxed filename format",
                                                 type=obs.OBS_TEXT_DEFAULT)
    auto_remux_menu = obs.obs_properties_add_group(props, "RemuxReplays", "Automatically remux replays",
                                                   obs.OBS_GROUP_CHECKABLE, auto_remux_props)

    remux_props = obs.obs_properties_create()

    remux_mode = obs.obs_properties_add_list(remux_props, "RemuxMode", "Mode",
                                             type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(remux_mode, "Standard", "standard")
    obs.obs_property_list_add_string(remux_mode, "Custom FFmpeg", "custom_ffmpeg")
    obs.obs_property_set_modified_callback(remux_mode, remux_settings_modified)

    obs.obs_property_set_modified_callback(replace_orig, remux_settings_modified)
    v_encoder = obs.obs_properties_add_list(remux_props, "RemuxVEncoder", "Encoding",
                                            type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(v_encoder, remux_settings_modified)

    obs.obs_property_list_add_string(v_encoder, "Copy encoding", "copy")

    obs.obs_property_list_add_string(v_encoder, "H.264 (libx264)", "libx264")

    obs.obs_properties_add_list(remux_props, "RemuxBitrateMode", "Bitrate mode", type=obs.OBS_COMBO_TYPE_LIST,
                                format=obs.OBS_COMBO_FORMAT_STRING)

    crf_slider = obs.obs_properties_add_int_slider(remux_props, "RemuxCRF", "CRF/CQ", min=0, max=51, step=1)
    br_slider = obs.obs_properties_add_int_slider(remux_props, "RemuxBitrate", "CBR (mbps)", min=1, max=100, step=1)

    h264_preset = obs.obs_properties_add_list(remux_props, "RemuxH264Preset", "Preset", type=obs.OBS_COMBO_TYPE_LIST,
                                              format=obs.OBS_COMBO_FORMAT_STRING)

    obs.obs_property_list_add_string(v_encoder, "H.264 (Nvidia NVENC)", "h264_nvenc")

    obs.obs_property_list_add_string(v_encoder, "av1 (SVT-AV1)", "libsvtav1")

    # obs.obs_property_list_add_string(v_encoder, "H.264 (AMD AMF)", "h264_amf")

    container = obs.obs_properties_add_list(remux_props, "RemuxFileContainer", "File container",
                                            type=obs.OBS_COMBO_TYPE_LIST,
                                            format=obs.OBS_COMBO_FORMAT_STRING)

    custom_ffmpeg = obs.obs_properties_add_text(remux_props, "RemuxCustomFFmpeg", "Custom FFmpeg command",
                                                obs.OBS_TEXT_DEFAULT)

    remux_info = obs.obs_properties_add_text(remux_props, "RemuxInfo", "For information refer to the <a "
                                                                       "href='https://trac.ffmpeg.org/wiki'>FFmpeg "
                                                                       "wiki</a>.", type=obs.OBS_TEXT_INFO)

    remux_menu = obs.obs_properties_add_group(props, "RemuxMenu", "Remux settings",
                                              obs.OBS_GROUP_NORMAL, remux_props)

    # ===== Manual remuxing =====
    manual_remux_props = obs.obs_properties_create()
    manual_remux_mode = obs.obs_properties_add_list(manual_remux_props, "ManualRemuxMode", "Mode",
                                                    type=obs.OBS_COMBO_TYPE_LIST,
                                                    format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(manual_remux_mode, remux_settings_modified)
    obs.obs_property_list_add_string(manual_remux_mode, "Single file", "file")
    obs.obs_property_list_add_string(manual_remux_mode, "Batch", "batch")

    obs.obs_properties_add_path(manual_remux_props, "ManualRemuxInputFile", "Input file", obs.OBS_PATH_FILE, "", "")
    obs.obs_properties_add_path(manual_remux_props, "ManualRemuxInputFolder", "Input folder", obs.OBS_PATH_DIRECTORY,
                                "",
                                SETTINGS["ReplayOutDir"])
    obs.obs_properties_add_button(manual_remux_props, "StartManualRemux", "Convert", manual_remux)

    manual_remux_menu = obs.obs_properties_add_group(props, "ManualRemuxMenu", "Manual remux",
                                                     obs.OBS_GROUP_NORMAL, manual_remux_props)

    return props


def file_sort_properties(props):
    # ===== FILE SORTING OPTIONS =====
    file_sorting_props = obs.obs_properties_create()

    sort_by_date = obs.obs_properties_add_bool(file_sorting_props, "SortByDate", "Sort files by date/time")

    obs.obs_property_set_modified_callback(sort_by_date, file_sorting_modified)
    # date_sort_scheme = obs.obs_properties_add_text(file_sorting_props, "DatetimeSortScheme", "Date sorting scheme",
    #                                                type=obs.OBS_TEXT_DEFAULT)
    # obs.obs_property_set_enabled(date_sort_scheme, False)
    datetime_sort_base = obs.obs_properties_add_list(file_sorting_props, "DatetimeSortBase", "Base date/time on",
                                                     type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(datetime_sort_base, "Replay buffer start", "replay_buffer_start")
    obs.obs_property_list_add_string(datetime_sort_base, "Replay buffer saved", "replay_buffer_saved")

    date_sort_scheme = obs.obs_properties_add_list(file_sorting_props, "DatetimeSortScheme", "Sorting scheme",
                                                   type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(date_sort_scheme, "YYYY-MM-DD/", "%Y-%m-%d/")
    obs.obs_property_list_add_string(date_sort_scheme, "YYYY/Month/WKDY_DD/", "%Y/%B/%a_%d/")


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

    props = file_sort_properties(props)
    props = remux_properties(props)

    obs.obs_properties_apply_settings(props, SCRIPT_PROPERTIES)

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
    global SETTINGS, CURRENT_BUFFER
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
            if SETTINGS["DatetimeSortBase"] == "replay_buffer_start":
                time = CURRENT_BUFFER["start_time"]
            elif SETTINGS["DatetimeSortBase"] == "replay_buffer_saved":
                time = datetime.datetime.now()
            date_path = time.strftime(SETTINGS["DatetimeSortScheme"])
            return_dir = os.path.join(return_dir, date_path)
    return return_dir


def on_event(event):
    global SETTINGS, CURRENT_BUFFER

    if event == obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED:
        start_time = datetime.datetime.now()
        CURRENT_BUFFER = {
            "start_time": datetime.datetime.now(),
            "saved_replays": []
        }
        print("===== REPLAY BUFFER STARTED =====", f"\n{start_time}\n")

    elif event == obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
        print("== Replay buffer saved")
        replay_path = get_latest_replay_path()
        print("Original file:", replay_path)

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
        print("New file path:", new_path)
        CURRENT_BUFFER["saved_replays"].append(new_path)
        if SETTINGS["PersistentReplayFilePath"] is not None:
            try:
                shutil.copyfile(new_path, SETTINGS["PersistentReplayFilePath"])
            except shutil.SameFileError:
                pass

        if SETTINGS["RemuxReplays"]:
            ffmpeg_input = new_path
            ffmpeg_cmd = generate_ffmpeg_cmd(ffmpeg_input)
            remux_thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,))
            remux_thread.start()

    elif event == obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STOPPED:
        end_time = datetime.datetime.now()
        print("\n===== REPLAY BUFFER STOPPED =====", f"\n{end_time}\nSaved replays:")
        for f in CURRENT_BUFFER["saved_replays"]:
            print(f)
