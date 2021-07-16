#!groovy

retry (10) {
    // load pipeline configuration into the environment
    httpRequest("${FEDORA_CI_PIPELINES_CONFIG_URL}/environment").content.split('\n').each { l ->
        l = l.trim(); if (l && !l.startsWith('#')) { env["${l.split('=')[0].trim()}"] = "${l.split('=')[1].trim()}" }
    }
}

def pipelineMetadata = [
    pipelineName: 'dist-git',
    pipelineDescription: 'Run tier-0 tests from dist-git',
    testCategory: 'functional',
    testType: 'tier0',
    maintainer: 'Fedora CI',
    docs: 'https://github.com/fedora-ci/dist-git-pipeline',
    contact: [
        irc: '#fedora-ci',
        email: 'ci@lists.fedoraproject.org'
    ],
]
def artifactId
def additionalArtifactIds
def testingFarmRequestId
def testingFarmResult
def xunit
def config
def hook

def repoUrlAndRef
def repoTests

def podYAML = """
spec:
  containers:
  - name: pipeline-agent
    # source: https://github.com/fedora-ci/jenkins-pipeline-library-agent-image
    image: quay.io/fedoraci/pipeline-library-agent:d41a11f
    tty: true
    alwaysPullImage: true
"""


pipeline {

    agent none

    libraries {
        lib("fedora-pipeline-library@24438110fdfe7700e3217c94be3b3c41d6f424a3")
    }

    options {
        buildDiscarder(logRotator(daysToKeepStr: env.DEFAULT_DAYS_TO_KEEP_LOGS, artifactNumToKeepStr: env.DEFAULT_ARTIFACTS_TO_KEEP))
        timeout(time: env.DEFAULT_PIPELINE_TIMEOUT_MINUTES, unit: 'MINUTES')
        skipDefaultCheckout(true)
    }

    parameters {
        string(name: 'ARTIFACT_ID', defaultValue: '', trim: true, description: '"koji-build:&lt;taskId&gt;" for Koji builds; Example: koji-build:46436038')
        string(name: 'ADDITIONAL_ARTIFACT_IDS', defaultValue: '', trim: true, description: 'A comma-separated list of additional ARTIFACT_IDs')
        string(name: 'TEST_PROFILE', defaultValue: env.FEDORA_CI_RAWHIDE_RELEASE_ID, trim: true, description: "A name of the test profile to use; Example: ${env.FEDORA_CI_RAWHIDE_RELEASE_ID}")
        string(name: 'TEST_REPO_URL', defaultValue: '', trim: true, description: '(optional) URL to the repository containing tests; followed by "#&lt;ref&gt;", where &lt;ref&gt; is a commit hash; Example: https://src.fedoraproject.org/tests/selinux#ff0784e36758f2fdce3201d907855b0dd74064f9')
    }

    environment {
        TESTING_FARM_API_KEY = credentials('testing-farm-api-key')
    }

    stages {
        stage('Prepare') {
            agent {
                label pipelineMetadata.pipelineName
            }
            steps {
                script {
                    artifactId = params.ARTIFACT_ID
                    additionalArtifactIds = params.ADDITIONAL_ARTIFACT_IDS
                    setBuildNameFromArtifactId(artifactId: artifactId, profile: params.TEST_PROFILE)

                    checkout scm
                    config = loadConfig(profile: params.TEST_PROFILE)

                    if (!artifactId) {
                        abort('ARTIFACT_ID is missing')
                    }

                    if (!TEST_REPO_URL) {
                        repoUrlAndRef = getRepoUrlAndRefFromTaskId("${getIdFromArtifactId(artifactId: artifactId)}")
                    } else {
                        repoUrlAndRef = [url: TEST_REPO_URL.split('#')[0], ref: TEST_REPO_URL.split('#')[1]]
                    }
                    repoTests = repoHasTests(repoUrl: repoUrlAndRef['url'], ref: repoUrlAndRef['ref'])
                    echo "repoTests: ${repoTests}"
                    echo "${repoTests['ciConfig']}"
                    if (!repoTests) {
                        abort("No dist-git tests (STI/FMF) were found in the repository ${repoUrlAndRef[0]}, skipping...")
                    }
                }
                sendMessage(type: 'queued', artifactId: artifactId, pipelineMetadata: pipelineMetadata, dryRun: isPullRequest())
            }
        }

        stage('Schedule Test') {
            agent {
                label pipelineMetadata.pipelineName
            }
            steps {
                script {
                    def artifacts = []
                    getIdFromArtifactId(artifactId: artifactId, additionalArtifactIds: additionalArtifactIds).split(',').each { taskId ->
                        if (taskId) {
                            artifacts.add([id: "${taskId}", type: "fedora-koji-build"])
                        }
                    }

                    def requestPayload = [
                        api_key: "${env.TESTING_FARM_API_KEY}",
                        test: [:],
                        environments: [
                            [
                                arch: "x86_64",
                                os: [ compose: "${config.compose}" ],
                                artifacts: artifacts
                            ]
                        ]
                    ]

                    if (repoTests['type'] == 'sti') {
                        // add playbooks to run
                        requestPayload['test']['sti'] = repoUrlAndRef
                        requestPayload['test']['sti']['playbooks'] = repoTests['files']
                    } else {
                        // tmt
                        requestPayload['test']['fmf'] = repoUrlAndRef
                        requestPayload['environments'][0]['tmt'] = [
                            context: config.tmt_context[getTargetArtifactType(artifactId)]
                        ]
                    }

                    hook = registerWebhook()
                    requestPayload['notification'] = ['webhook': [url: hook.getURL()]]

                    // def response = submitTestingFarmRequest(payloadMap: requestPayload)
                    // testingFarmRequestId = response['id']
                }
                sendMessage(type: 'running', artifactId: artifactId, pipelineMetadata: pipelineMetadata, dryRun: isPullRequest())
            }
        }

        stage('Wait for Test Results') {
            agent none
            steps {
                script {
                    // def response = waitForTestingFarm(requestId: testingFarmRequestId, hook: hook)
//                     def response = """
// {"id": "f604122f-d9fc-45f5-985d-01f756bad212", "user_id": "c4af7afe-b95e-4cf1-b989-9c458f0eecf0", "test": {"fmf": {"name": null, "path": ".", "ref": "79a83d4b834c8a2f24155853910252b752b36aa3", "url": "https://src.fedoraproject.org/rpms/perl-PDF-Builder"}, "script": null, "sti": null}, "state": "complete", "environments_requested": [{"arch": "x86_64", "artifacts": [{"id": "71991431", "packages": null, "type": "fedora-koji-build"}], "os": {"compose": "Fedora-Rawhide"}, "pool": null, "settings": null, "tmt": {"context": {"arch": "x86_64", "distro": "fedora-35", "trigger": "build"}}, "variables": null}], "notes": [{"level": "info", "message": "tf-tmt/dispatch-1626438582-61c09701"}], "result": {"overall": "passed", "summary": null, "xunit": "<testsuites overall-result=\"passed\"><properties><property name=\"baseosci.overall-result\" value=\"passed\"/></properties><testsuite name=\"/plans/sanity\" result=\"passed\" tests=\"1\"><logs><log guest-setup-stage=\"artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/artifact-installation-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c\" name=\"build installation\" schedule-stage=\"guest-setup\"/><log guest-setup-stage=\"pre_artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/guest-setup-output-pre-artifact-installation.txt\" name=\"guest setup\" schedule-stage=\"guest-setup\"/><log guest-setup-stage=\"post_artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/guest-setup-output-post-artifact-installation.txt\" name=\"guest setup\" schedule-stage=\"guest-setup\"/></logs><properties><property name=\"baseosci.result\" value=\"passed\"/></properties><testcase name=\"/tests/upstream-tests\" result=\"passed\"><properties><property name=\"baseosci.arch\" value=\"x86_64\"/><property name=\"baseosci.connectable_host\" value=\"172.31.31.245\"/><property name=\"baseosci.distro\" value=\"Fedora-Rawhide\"/><property name=\"baseosci.status\" value=\"Complete\"/><property name=\"baseosci.testcase.source.url\" value=\"\"/><property name=\"baseosci.variant\" value=\"\"/></properties><logs><log href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/work-sanityP6fJaZ/plans/sanity/execute/data/tests/upstream-tests\" name=\"log_dir\" schedule-stage=\"running\"/><log href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/work-sanityP6fJaZ/plans/sanity/execute/data/tests/upstream-tests/output.txt\" name=\"testout.log\" schedule-stage=\"running\"/></logs><testing-environment name=\"requested\"><property name=\"arch\" value=\"x86_64\"/><property name=\"compose\" value=\"Fedora-Rawhide\"/><property name=\"snapshots\" value=\"False\"/></testing-environment><testing-environment name=\"provisioned\"><property name=\"arch\" value=\"x86_64\"/><property name=\"compose\" value=\"Fedora-Rawhide\"/><property name=\"snapshots\" value=\"False\"/></testing-environment></testcase></testsuite></testsuites>"}, "run": {"artifacts": "http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212", "console": null, "stages": null}, "created": "2021-07-16 12:29:29.968488", "updated": "2021-07-16 12:29:29.968501"}
//                     """
                    // testingFarmResult = response.apiResponse
                    xunit = """
<testsuites overall-result=\"passed\"><properties><property name=\"baseosci.overall-result\" value=\"passed\"/></properties><testsuite name=\"/plans/sanity\" result=\"passed\" tests=\"1\"><logs><log guest-setup-stage=\"artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/artifact-installation-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c\" name=\"build installation\" schedule-stage=\"guest-setup\"/><log guest-setup-stage=\"pre_artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/guest-setup-output-pre-artifact-installation.txt\" name=\"guest setup\" schedule-stage=\"guest-setup\"/><log guest-setup-stage=\"post_artifact_installation\" href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/guest-setup-bc8a1c8c-8adc-414b-9242-f3f6d8653f2c/guest-setup-output-post-artifact-installation.txt\" name=\"guest setup\" schedule-stage=\"guest-setup\"/></logs><properties><property name=\"baseosci.result\" value=\"passed\"/></properties><testcase name=\"/tests/upstream-tests\" result=\"passed\"><properties><property name=\"baseosci.arch\" value=\"x86_64\"/><property name=\"baseosci.connectable_host\" value=\"172.31.31.245\"/><property name=\"baseosci.distro\" value=\"Fedora-Rawhide\"/><property name=\"baseosci.status\" value=\"Complete\"/><property name=\"baseosci.testcase.source.url\" value=\"\"/><property name=\"baseosci.variant\" value=\"\"/></properties><logs><log href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/work-sanityP6fJaZ/plans/sanity/execute/data/tests/upstream-tests\" name=\"log_dir\" schedule-stage=\"running\"/><log href=\"http://artifacts.dev.testing-farm.io/f604122f-d9fc-45f5-985d-01f756bad212/work-sanityP6fJaZ/plans/sanity/execute/data/tests/upstream-tests/output.txt\" name=\"testout.log\" schedule-stage=\"running\"/></logs><testing-environment name=\"requested\"><property name=\"arch\" value=\"x86_64\"/><property name=\"compose\" value=\"Fedora-Rawhide\"/><property name=\"snapshots\" value=\"False\"/></testing-environment><testing-environment name=\"provisioned\"><property name=\"arch\" value=\"x86_64\"/><property name=\"compose\" value=\"Fedora-Rawhide\"/><property name=\"snapshots\" value=\"False\"/></testing-environment></testcase></testsuite></testsuites>
"""
                }
            }
        }

        stage('Process Test Results (XUnit)') {
            when {
                beforeAgent true
                expression { xunit }
            }
            agent {
                kubernetes {
                    yaml podYAML
                    defaultContainer 'pipeline-agent'
                }
            }
            steps {
                script {
                    // Convert Testing Farm XUnit into JUnit and store the result in Jenkins
                    writeFile file: 'tfxunit.xml', text: "${xunit}"
                    sh script: "tfxunit2junit --docs-url ${pipelineMetadata['docs']} tfxunit.xml > xunit.xml"
                    junit(allowEmptyResults: true, keepLongStdio: true, testResults: 'xunit.xml')
                }
            }
        }
    }

    post {
        // always {
        //     // evaluateTestingFarmResults(testingFarmResult)
        // }
        aborted {
            script {
                if (isTimeoutAborted(timeout: env.DEFAULT_PIPELINE_TIMEOUT_MINUTES, unit: 'MINUTES')) {
                    sendMessage(type: 'error', artifactId: artifactId, errorReason: 'Timeout has been exceeded, pipeline aborted.', pipelineMetadata: pipelineMetadata, dryRun: isPullRequest())
                }
            }
        }
        success {
            sendMessage(type: 'complete', artifactId: artifactId, pipelineMetadata: pipelineMetadata, xunit: xunit, ciConfig: repoTests['ciConfig'], dryRun: isPullRequest())
        }
        failure {
            sendMessage(type: 'error', artifactId: artifactId, pipelineMetadata: pipelineMetadata, dryRun: isPullRequest())
        }
        unstable {
            sendMessage(type: 'complete', artifactId: artifactId, pipelineMetadata: pipelineMetadata, xunit: xunit, ciConfig: repoTests['ciConfig'], dryRun: isPullRequest())
        }
    }
}
