# -*- coding: utf-8 -*-

import sublime, sublime_plugin
from subprocess import Popen, PIPE, call
import os
import json
import sys

server_port = 9166

server_path = None
client_path = None

server_process = None

def open_file(filename):
    if sys.platform == "win32":
        os.startfile(filename)
    else:
        opener ="open" if sys.platform == "darwin" else "xdg-open"
        call([opener, filename])

def start_server():
    global server_process

    if not (server_process is None) and server_process.poll() is None:
        server_process.terminate()

    settings = sublime.load_settings('DKit.sublime-settings')
    global server_port
    server_port = settings.get('dcd_port', 9166)
    dcd_path = settings.get('dcd_path', '')

    global server_path
    global client_path
    server_path = os.path.join(dcd_path, 'dcd-server')
    client_path = os.path.join(dcd_path, 'dcd-client')

    if not os.path.exists(server_path):
        sublime.error_message('DCD server doesn\'t exist in the path specified:\n' + server_path + '\n\nSetup the path in DCD package settings and then restart sublime to get things working.')
        return False

    if not os.path.exists(client_path):
        sublime.error_message('DCD client doesn\'t exist in the path specified:\n' + client_path + '\n\nSetup the path in DCD package settings and then restart sublime to get things working.')
        return False

    include_paths = settings.get('include_paths')
    include_paths = ['-I' + p for p in include_paths]

    args = [server_path]
    args.extend(include_paths)
    args.extend(['-p' + str(server_port)])

    print('Restarting DCD server...')
    server_process = Popen(args)
    return True

class DCD(sublime_plugin.EventListener):
    def __exit__(self, type, value, traceback):
        global server_process
        if not (server_process is None) and server_process.poll() is None:
            server_process.terminate()

    def on_query_completions(self, view, prefix, locations):
        if view.scope_name(locations[0]).strip() != 'source.d':
            return

        global server_process
        if server_process is None:
            start_server()

        position = locations[0]
        position = position - len(prefix)
        if (view.substr(position) != '.'):
            position = locations[0]

        response = self.request_completions(view.substr(sublime.Region(0, view.size())), position)
        return (response, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    def request_completions(self, file, position):
        args = [client_path, '-c' + str(position), '-p' + str(server_port)]
        client = Popen(args, stdin=PIPE, stdout=PIPE)

        output = client.communicate(file.encode())
        output = output[0].decode('utf-8').splitlines()
        if len(output) == 0:
            return []

        completions_type = output[0]
        del output[0]

        if (completions_type == 'identifiers'):
            output = [self.parse_identifiers(line) for line in output]
        elif (completions_type == 'calltips'):
            output = [self.parse_calltips(line) for line in output]
        else:
            output = []

        return output

    def parse_identifiers(self, line):
        parts = line.split('\t')

        if len(parts) == 2:
            cmap = {
                'c': 'class',
                'i': 'interface',
                's': 'struct',
                'u': 'union',
                'v': 'variable',
                'm': 'member variable',
                'k': 'keyword',
                'f': 'function',
                'g': 'enum',
                'e': 'enum member',
                'P': 'package',
                'M': 'module',
                'a': 'array',
                'A': 'associative array',
                'l': 'alias'}

            visible_name = parts[0] + '\t' + cmap[parts[1]]
            if parts[1] == 'f':
                text = parts[0]
            else:
                text = parts[0]

            return visible_name, text

        else:
            return None

    def parse_calltips(self, line):
        index = line.find('(')
        if index >= 0:
            visible_name = line
            text = line[index + 1 : -1]
        else:
            visible_name = line
            text = line
        return visible_name, text

class DcdStartServerCommand(sublime_plugin.ApplicationCommand):
    def run(self):
        start_server()

class DcdUpdateIncludePathsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        Popen([client_path, '--clearCache']).wait()

        include_paths = self.view.settings().get('include_paths', [])

        if len(include_paths) > 0:
            args = [client_path]
            args.extend(['-I' + p for p in include_paths])

            Popen(args).wait()

class DubListInstalledCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        try:
            dub = Popen(['dub', 'list-installed'], stdin=PIPE, stdout=PIPE)
            output = dub.communicate()
            output = output[0].splitlines()
            del output[0]
            output = [o.strip() for o in output if len(o.strip()) > 0]
            self.view.window().show_quick_panel(output, None)
        except OSError:
            sublime.error_message('Unable to run DUB. Make sure that it is installed correctly and on your PATH environment variable')

class DubCreatePackageCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.new_file()
        view.set_name('package.json')
        view.set_syntax_file('Packages/JavaScript/JSON.tmLanguage')
        view.run_command('dub_create_package_text')

class DubCreatePackageTextCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        package = """{
  "name": "project-name",
  "description": "An example project skeleton",
  "homepage": "http://example.org",
  "copyright": "Copyright (c) 2013, Your Name",
  "authors": [],
  "dependencies": {},
  "targetType": "executable"
}"""
        self.view.insert(edit, 0, package)

class DubCreateProjectFromPackageCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        package_folder = os.path.dirname(view.file_name())
        package_file = os.path.basename(view.file_name())
        if package_file != 'package.json':
            sublime.error_message('Please open the `package.json` file and then run the command again.')
            return

        dub = Popen(['dub', 'describe'], stdin=PIPE, stdout=PIPE, cwd=package_folder)
        description = dub.communicate()
        description = description[0].decode('utf-8')
        description = json.loads(description)

        include_paths = set()

        main_package = description['mainPackage']

        for package in description['packages']:
            base_path = package['path']
            for f in package['files']:
                folder = os.path.join(base_path, os.path.dirname(f['path']))
                include_paths.add(folder)

        folders = [{'path': folder} for folder in include_paths]
        settings = {'include_paths': [f for f in include_paths]}
        project_settings = {'folders': folders, 'settings': settings}

        project_file = os.path.join(package_folder, main_package + '.sublime-project')
        if os.path.exists(project_file):
            sublime.error_message('A Sublime Text project already exists in the folder. Aborting.') #TODO: change into something more user-friendly
            return

        f = open(project_file, "w")
        f.write(json.dumps(project_settings, indent=4))
        f.close()

        open_file(project_file)
