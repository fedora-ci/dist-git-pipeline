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
def config
def hook
def runUrl

def repoUrlAndRef
def repoTests
def testPlan

def reportSeparately = false


pipeline {

    agent none

    libraries {
        lib("fedora-pipeline-library@${env.PIPELINE_LIBRARY_VERSION}")
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
        string(name: 'TEST_PLAN', defaultValue: '', trim: true, description: '(optional) name of the test plan to run; Example: /plans/regression')
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
                    testPlan = params.TEST_PLAN

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
                    repoTests = repoHasTests(repoUrl: repoUrlAndRef['url'], ref: repoUrlAndRef['ref'], context: config.tmt_context[getTargetArtifactType(artifactId)])

                    if (!repoTests) {
                        abort("No dist-git tests (STI/TMT) were found in the repository ${repoUrlAndRef[0]}, skipping...")
                    }
                    if (!testPlan) {
                        // it doesn't make sense to report results separately if we are running only one test plan
                        reportSeparately = repoTests.ciConfig.get('resultsdb-testcase') == 'separate'
                    } else {
                        pipelineMetadata['testType'] = testPlan
                    }
                    if (reportSeparately && repoTests['type'] == 'fmf') {
                        // we want to report results separately, so we will just run this job for each test plan individually
                        repoTests['plans'].each { plan ->
                            build(
                                job: "${JOB_NAME}",
                                wait: false,
                                parameters: [
                                    string(name: 'ARTIFACT_ID', value: params.ARTIFACT_ID),
                                    string(name: 'ADDITIONAL_ARTIFACT_IDS', value: params.ADDITIONAL_ARTIFACT_IDS),
                                    string(name: 'TEST_PROFILE', value: params.TEST_PROFILE),
                                    string(name: 'TEST_REPO_URL', value: params.TEST_REPO_URL),
                                    string(name: 'TEST_PLAN', value: plan),
                                ]
                            )
                        }
                        abort("Separate tasks were scheduled for all test plans.")
                    }
                }
                // sendMessage(
                //     type: 'queued',
                //     artifactId: artifactId,
                //     pipelineMetadata: pipelineMetadata,
                //     dryRun: isPullRequest()
                // )
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
                                variables: [
                                    KOJI_TASK_ID: "${getIdFromArtifactId(artifactId: artifactId)}"
                                ],
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
                        if (testPlan) {
                            requestPayload['test']['fmf']['name'] = testPlan
                        }
                    }

                    hook = registerWebhook()
                    requestPayload['notification'] = ['webhook': [url: hook.getURL()]]

                    def response = submitTestingFarmRequest(payloadMap: requestPayload)
                    testingFarmRequestId = response['id']
                }
                sendMessage(
                    type: 'running',
                    artifactId: artifactId,
                    pipelineMetadata: pipelineMetadata,
                    dryRun: isPullRequest()
                )
            }
        }

        stage('Wait for Test Results') {
            agent none
            steps {
                script {
                    def response = waitForTestingFarm(requestId: testingFarmRequestId, hook: hook)
                    testingFarmResult = response.apiResponse

                    runUrl = "${FEDORA_CI_TESTING_FARM_ARTIFACTS_URL}/${testingFarmRequestId}"
                }
            }
        }
    }

    post {
        always {
            evaluateTestingFarmResults(testingFarmResult)
        }
        aborted {
            script {
                if (isTimeoutAborted(timeout: env.DEFAULT_PIPELINE_TIMEOUT_MINUTES, unit: 'MINUTES')) {
                    sendMessage(
                        type: 'error',
                        artifactId: artifactId,
                        errorReason: 'Timeout has been exceeded, pipeline aborted.',
                        pipelineMetadata: pipelineMetadata,
                        dryRun: isPullRequest()
                    )
                }
            }
        }
        success {
            script {
                sendMessage(
                    type: 'complete',
                    artifactId: artifactId,
                    pipelineMetadata: pipelineMetadata,
                    runUrl: runUrl,
                    dryRun: isPullRequest()
                )
            }
        }
        failure {
            sendMessage(
                type: 'error',
                artifactId: artifactId,
                pipelineMetadata: pipelineMetadata,
                dryRun: isPullRequest()
            )
        }
        unstable {
            script {
                sendMessage(
                    type: 'complete',
                    artifactId: artifactId,
                    pipelineMetadata: pipelineMetadata,
                    runUrl: runUrl,
                    dryRun: isPullRequest()
                )
            }
        }
    }
}
