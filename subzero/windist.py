# This file was originally taken from cx_Freeze by Anthony Tuininga, and is licensed under the  PSF license.

import distutils.command.bdist_msi
import distutils.errors
import distutils.util
import msilib
import ntpath
import os
import re
import shutil
from io import StringIO

import PyRTF
import pywix
from pkg_resources import resource_filename

from subzero.dist import build_exe

__all__ = ["bdist_msi"]


class bdist_msi(distutils.command.bdist_msi.bdist_msi):
    user_options = distutils.command.bdist_msi.bdist_msi.user_options + [
        ('add-to-path=', None, 'add target dir to PATH environment variable'),
        ('upgrade-code=', None, 'upgrade code to use'),
        ('initial-target-dir=', None, 'initial target directory'),
        ('target-name=', None, 'name of the file to create'),
        ('directories=', None, 'list of 3-tuples of directories to create'),
        ('data=', None, 'dictionary of data indexed by table name'),
        ('product-code=', None, 'product code to use')
    ]

    def _split_path(self, path):
        folders = []
        while 1:
            path, folder = os.path.split(path)

            if folder != "":
                folders.append(folder)
            else:
                if path != "":
                    folders.append(path)

                break

        folders.reverse()

        return folders

    def _license_text(self, license_file):
        """
        Generates rich text given a license file-like object
        :param license_file: file-like object
        :return:
        """
        wordpad_header = r'''{\rtf1\ansi\ansicpg1252\deff0\nouicompat\deflang1033{\fonttbl{\f0\fnil\fcharset255 Times New Roman;}
{\*\generator Riched20 10.0.14393}\viewkind4\uc1'''.replace('\n', '\r\n')
        center_space = '            '

        pattern = re.compile(r'{}\s*'.format(center_space))

        r = PyRTF.Renderer()

        doc = PyRTF.Document()
        ss = doc.StyleSheet
        sec = PyRTF.Section()
        doc.Sections.append(sec)

        is_blank = False
        paragraph_text = ['']
        for line in license_file:
            if not line or line.isspace():
                is_blank = True
            if is_blank:
                # first element of paragraph_text is left-aligned, subsequent elements are centered
                is_centered = False
                for sec_line in paragraph_text:
                    if is_centered:
                        para_props = PyRTF.ParagraphPS(alignment=PyRTF.ParagraphPS.CENTER)
                        p = PyRTF.Paragraph(ss.ParagraphStyles.Normal, para_props)
                        p.append(sec_line)
                        sec.append(p)
                    elif sec_line:  # first element may be nothing, but not whitespace
                        sec.append(sec_line)
                    is_centered = True
                is_blank = False
                paragraph_text = ['']
            if line.startswith(center_space):
                paragraph_text.append(line.strip())
                is_blank = True
            else:
                paragraph_text[0] += ' ' + line
                paragraph_text[0] = paragraph_text[0].strip()

        f = StringIO()
        f.write(wordpad_header)
        r.Write(doc, f)

        return f.getvalue()

    def finalize_options(self):
        initial_set = (self.distribution.author and self.distribution.name) and not self.initial_target_dir

        distutils.command.bdist_msi.bdist_msi.finalize_options(self)
        name = self.distribution.get_name()
        fullname = self.distribution.get_fullname()
        author = self.distribution.get_author()
        if self.initial_target_dir is None:
            if distutils.util.get_platform() == "win-amd64":
                programFilesFolder = "ProgramFiles64Folder"
            else:
                programFilesFolder = "ProgramFilesFolder"
            self.initial_target_dir = r"[{}]\{}\{}".format(programFilesFolder, author, name)
        if self.add_to_path is None:
            self.add_to_path = False
        if self.target_name is None:
            self.target_name = fullname
        if not self.target_name.lower().endswith(".msi"):
            platform = distutils.util.get_platform().replace("win-", "")
            self.target_name = "%s-%s.msi" % (self.target_name, platform)
        if not os.path.isabs(self.target_name):
            self.target_name = os.path.join(self.dist_dir, self.target_name)
        if self.directories is None:
            self.directories = []
        if self.data is None:
            self.data = {}

        # attempt to find the build directory
        build_found = False
        for i in range(0, 3):
            if os.path.basename(self.bdist_dir) == 'build':
                build_found = True
                break
            else:
                self.bdist_dir = ntpath.dirname(self.bdist_dir)

        if not build_found:
            raise EnvironmentError('Unable to identify build directory!')

        self.bdist_dir = os.path.join(self.bdist_dir, build_exe.build_dir())
        self.build_temp = os.path.join(ntpath.dirname(self.bdist_dir), 'temp' + ntpath.basename(self.bdist_dir)[3:])
        self.height = 270

    def initialize_options(self):
        distutils.command.bdist_msi.bdist_msi.initialize_options(self)
        self.upgrade_code = None
        self.product_code = None
        self.add_to_path = None
        self.initial_target_dir = None
        self.target_name = None
        self.directories = None
        self.data = None
        self.shortcuts = None

        # TODO: Parse other types of license files
        for file in ['LICENSE', 'LICENSE.txt']:
            if os.path.isfile(file):
                self.license_text = self._license_text(open(file))
                break

    def run(self):
        # self.skip_build = True
        if not self.skip_build:
            self.run_command('build_exe')

        self.mkpath(self.dist_dir)
        fullname = self.distribution.get_fullname()
        if os.path.exists(self.target_name):
            os.unlink(self.target_name)
        metadata = self.distribution.metadata
        author = metadata.author or metadata.maintainer or "UNKNOWN"
        version = metadata.get_version()
        sversion = "%d.%d.%d" % distutils.version.StrictVersion(version).version
        if self.product_code is None:
            self.product_code = msilib.gen_uuid()

        current_directory = os.getcwd()

        shutil.copy(resource_filename('subzero.resources', 'Product.wxs'), self.build_temp)
        print(pywix.call_wix_command(['heat', 'dir', self.bdist_dir, '-gg', '-sfrag', '-sreg',
                                      '-out', os.path.join(self.build_temp, 'Directory.wxs')]))

        files = ['Product.wxs', 'Directory.wxs']

        candle_arguments = ['candle']
        for file in files:
            candle_arguments.append(file)

        light_arguments = ['light']
        for file in files:
            light_arguments.append('{}.wixobj'.format(os.path.splitext(file)[0]))

        light_arguments.extend(['-out', os.path.join(current_directory, self.target_name)])

        os.chdir(self.build_temp)
        print(pywix.call_wix_command(candle_arguments))
        print(pywix.call_wix_command(light_arguments))

        os.chdir(current_directory)
