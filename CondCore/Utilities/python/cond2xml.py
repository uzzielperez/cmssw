
import os
import shutil
import sys
import time
import glob
import importlib
import logging
import subprocess

# as we need to load the shared lib from here, make sure it's in our path:
if os.path.join( os.environ['CMSSW_BASE'], 'src') not in sys.path:
   sys.path.append( os.path.join( os.environ['CMSSW_BASE'], 'src') )

# -------------------------------------------------------------------------------------------------------

payload2xmlCodeTemplate = """

#include "CondCore/Utilities/interface/Payload2XMLModule.h"
#include "CondCore/Utilities/src/CondFormats.h"

PAYLOAD_2XML_MODULE( %s ){
  PAYLOAD_2XML_CLASS( %s );
}

""" 

buildFileTemplate = """
<flags CXXFLAGS="-Wno-sign-compare -Wno-unused-variable -Os"/>
<library   file="%s" name="%s">
  <use   name="CondCore/Utilities"/>
  <use   name="boost_python"/>
</library>
<export>
  <lib   name="1"/>
</export>
"""

# helper function
def sanitize(typeName):
    return typeName.replace(' ','').replace('<','_').replace('>','')

class CondXmlProcessor(object):

    def __init__(self, condDBIn):
    	self.conddb = condDBIn
    	#self._pl2xml_isPrepared = False

	if not os.path.exists( os.path.join( os.environ['CMSSW_BASE'], 'src') ):
	   raise Exception("Looks like you are not running in a CMSSW developer area, $CMSSW_BASE/src/ does not exist")

	self.fakePkgName = "fakeSubSys4pl/fakePkg4pl"
	self._pl2xml_tmpDir = os.path.join( os.environ['CMSSW_BASE'], 'src', self.fakePkgName )

	self.doCleanup = False

    def __del__(self):

    	if self.doCleanup: 
           shutil.rmtree( '/'.join( self._pl2xml_tmpDir.split('/')[:-1] ) )
        return 

    def discover(self, payloadType):

        libName = 'pluginUtilities_payload2xml.so'
        # first search: developer area or main release
        libDir = os.path.join( os.environ["CMSSW_BASE"], 'lib', os.environ["SCRAM_ARCH"] )
        devLibDir = libDir
        libPath = os.path.join( devLibDir, libName )
        devCheckout = ("CMSSW_RELEASE_BASE" in os.environ)
        if not os.path.exists( libPath ) and devCheckout:
           # main release ( for dev checkouts )
           libDir = os.path.join( os.environ["CMSSW_RELEASE_BASE"], 'lib', os.environ["SCRAM_ARCH"] )
           libPath = os.path.join( libDir, libName )
        if not os.path.exists( libPath ):
           # it should never happen!
           raise Exception('No built-in library found with XML converters.')
        module = importlib.import_module( libName.replace('.so', '') )
        functors = dir(module)
        funcName = payloadType+'2xml'
        if funcName in functors:
           logging.info('XML converter for payload class %s found in the built-in library.' %payloadType)
           return getattr( module, funcName)
        if not devCheckout:
           # give-up if it is a read-only release...
           raise Exception('No XML converter suitable for payload class %s has been found in the built-in library.')
        localLibName = 'plugin%s_payload2xml.so' %sanitize( payloadType )
        localLibPath = os.path.join( devLibDir, localLibName )
        if os.path.exists( localLibPath ):
           logging.info('Found local library with XML converter for class %s' %payloadType )
           module = importlib.import_module( localLibName.replace('.so', '') )
           return getattr( module, funcName)
        logging.warning('No XML converter for payload class %s found in the built-in library.' %payloadType)
        return None

    def prepPayload2xml(self, payloadType):
    
        converter = self.discover(payloadType)
	if converter: return converter

        #otherwise, go for the code generation in the local checkout area.
    	startTime = time.time()

        libName = "%s_payload2xml" %sanitize(payloadType)
        pluginName = 'plugin%s' % libName
        tmpLibName = "Tmp_payload2xml"
        tmpPluginName = 'plugin%s' %tmpLibName
         
        libDir = os.path.join( os.environ["CMSSW_BASE"], 'lib', os.environ["SCRAM_ARCH"] )
        tmpLibFile = os.path.join( libDir,tmpPluginName+'.so' )
        code = payload2xmlCodeTemplate %(pluginName,payloadType) 
    
        tmpSrcFileName = 'Local_2XML.cpp' 
        tmpDir = self._pl2xml_tmpDir
        if ( os.path.exists( tmpDir ) ) :
           msg = '\nERROR: %s already exists, please remove if you did not create that manually !!' % tmpDir
	   raise Exception(msg)

        logging.debug('Creating temporary package %s' %self._pl2xml_tmpDir)
        os.makedirs( tmpDir+'/plugins' )
    
        buildFileName = "%s/plugins/BuildFile.xml" % (tmpDir,)
        with open(buildFileName, 'w') as buildFile:
        	 buildFile.write( buildFileTemplate %(tmpSrcFileName,tmpLibName) )
    	 	 buildFile.close()
    
        tmpSrcFilePath = "%s/plugins/%s" % (tmpDir, tmpSrcFileName,)
        with open(tmpSrcFilePath, 'w') as codeFile:
        	 codeFile.write(code)
    	 	 codeFile.close()
    
    	cmd = "source /afs/cern.ch/cms/cmsset_default.sh;"
    	cmd += "(cd %s ; scram b 2>&1 >build.log)" %tmpDir
        pipe = subprocess.Popen( cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT )
        out, err = pipe.communicate()
        ret = pipe.returncode

	buildTime = time.time()-startTime
        logging.info("Building done in %s sec., return code from build: %s" %(buildTime,ret) )

	if (ret != 0):
           return None

        libFile = os.path.join(libDir,pluginName + '.so')
        shutil.copyfile(tmpLibFile,libFile)

        module =  importlib.import_module( pluginName )
        funcName = payloadType+'2xml'
        functor = getattr( module, funcName ) 
        self.doCleanup = True
        return functor
    
    def payload2xml(self, session, payload):
    
        Payload = session.get_dbtype(self.conddb.Payload)
        # get payload from DB:
        result = session.query(Payload.data, Payload.object_type).filter(Payload.hash == payload).one()
        data, plType = result
        logging.info('Found payload of type %s' %plType)
    
        convFuncName = sanitize(plType)+'2xml'
        xmlConverter = self.prepPayload2xml(plType)

        obj = xmlConverter()
        resultXML = obj.write( str(data) )
        print resultXML    
    
