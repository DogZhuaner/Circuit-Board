function trapTeachingFocus(event) {
    const elements = Array.from(this.$refs.dialog.querySelectorAll('button:not(:disabled), a[href], summary, input:not(:disabled), textarea:not(:disabled), select:not(:disabled)'))
        .filter(el => el.offsetWidth > 0);
    const edge = event.shiftKey ? elements[0] : elements[elements.length - 1];
    if (elements.length && (document.activeElement === edge || (event.shiftKey && document.activeElement === this.$refs.dialog))) {
        event.preventDefault();
        (event.shiftKey ? elements[elements.length - 1] : elements[0]).focus();
    }
}

async function teachingApi(path, method = 'GET', body) {
    const options = { method, cache: 'no-store' };
    if (body) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(body);
    }
    const response = await fetch('api/' + path, options);
    if (response.status === 401) this.loginRequired = true;
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || '请求失败，请重试');
    return data;
}

function teachingLocalTime(date) {
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

const TeachingDialog = {
    template: '#teaching-dialog-template',
    props: { mode: String, signedIn: Boolean, initialExam: Object, locked: Boolean },
    emits: ['close', 'saved'],
    data() {
        const now = new Date();
        const exam = this.initialExam;
        return {
            form: exam ? {
                class_ids: exam.classes.map(c => c.id), test_name: exam.test_name, exam_content: exam.exam_content || '',
                rule_filename: '', publish_time: exam.publish_time.slice(0, 16), deadline_time: exam.deadline_time.slice(0, 16)
            } : { class_ids: [], test_name: '', exam_content: '', rule_filename: '',
                publish_time: teachingLocalTime(now), deadline_time: teachingLocalTime(new Date(now.getTime() + 3600000)) },
            files: [], groups: [], students: [], selected: null, ready: false,
            newName: '', editName: '', members: true, search: '', published: false,
            loginRequired: !this.signedIn, busy: false, loading: false, notice: '', error: ''
        };
    },
    computed: {
        exam() { return this.mode === 'exam'; },
        changes() {
            const exam = this.initialExam;
            const changes = {};
            if (!exam) return changes;
            if (this.form.test_name !== exam.test_name) changes.test_name = this.form.test_name;
            for (const key of ['publish_time', 'deadline_time']) {
                if (this.form[key] !== exam[key].slice(0, 16)) changes[key] = this.form[key];
            }
            if (this.form.exam_content !== (exam.exam_content || '')) changes.exam_content = this.form.exam_content;
            if (this.form.rule_filename) changes.rule_filename = this.form.rule_filename;
            const original = exam.classes.map(group => group.id);
            const ids = this.form.class_ids;
            if (original.length !== ids.length || ids.some(id => !original.includes(id))) changes.class_ids = ids;
            return changes;
        },
        canSaveExam() {
            if (this.busy || this.loading || this.locked) return false;
            if (!this.initialExam) return this.files.length && this.form.class_ids.length;
            return Object.keys(this.changes).length && (!this.changes.class_ids || this.changes.class_ids.length);
        },
        current() { return this.groups.find(group => group.id === this.selected); },
        filtered() {
            return this.students.filter(s => Boolean(s.member) === this.members &&
                (s.name.includes(this.search) || String(s.sno).includes(this.search)));
        }
    },
    async mounted() {
        this.$refs.dialog.focus();
        if (this.loginRequired) return;
        this.loading = true;
        try {
            if (this.exam) {
                const [rules, roster] = await Promise.all([this.api('rules'), this.api('classes')]);
                this.files = rules.files.filter(file => file.rule_count > 0);
                this.groups = roster.classes;
            } else {
                this.groups = (await this.api('classes')).classes;
                if (this.groups.length) await this.choose(this.groups[0].id);
            }
        } catch (error) {
            this.error = error.message;
        } finally {
            this.loading = false;
        }
    },
    methods: {
        close() {
            if (!this.busy) this.$emit('close');
        },
        trapFocus: trapTeachingFocus,
        api: teachingApi,
        async mutate(action) {
            if (this.busy || this.loading) return;
            this.busy = true;
            this.notice = this.error = '';
            try { await action(); }
            catch (error) { this.error = error.message; }
            finally { this.busy = false; }
        },
        publish() {
            if (!this.canSaveExam) return;
            if (this.form.deadline_time <= this.form.publish_time) {
                this.error = '截止时间必须晚于开始时间';
                return;
            }
            return this.mutate(async () => {
                if (this.initialExam) {
                    await this.api('exams/' + this.initialExam.id, 'PATCH', this.changes);
                    this.$emit('saved', '考试修改已保存');
                    this.$emit('close');
                    return;
                }
                const data = await this.api('create_exam', 'POST', this.form);
                this.$emit('saved', '考试已发布');
                this.published = true;
                this.notice = '考试已发布，考试 ID 为 ' + data.exam_id;
            });
        },
        async choose(id) {
            this.selected = id;
            this.ready = false;
            this.loading = true;
            this.error = '';
            this.search = '';
            this.members = true;
            try {
                const data = await this.api('classes/' + id);
                if (this.selected !== id) return;
                this.editName = data.group.name;
                this.students = data.students;
                this.current.name = data.group.name;
                this.current.count = data.students.filter(s => s.member).length;
                this.ready = true;
            } catch (error) {
                if (this.selected === id) this.error = error.message;
            } finally {
                if (this.selected === id) this.loading = false;
            }
        },
        createGroup() {
            return this.mutate(async () => {
                const name = this.newName;
                const data = await this.api('classes', 'POST', { name });
                this.groups.push({ id: data.id, name, count: 0 });
                this.newName = '';
                await this.choose(data.id);
                this.notice = '已创建「' + name + '」';
            });
        },
        renameGroup() {
            return this.mutate(async () => {
                const name = this.editName;
                await this.api('classes/' + this.selected, 'PATCH', { name });
                this.current.name = name;
                this.notice = '班级名称已保存';
            });
        },
        setMember(student) {
            return this.mutate(async () => {
                const adding = !student.member;
                await this.api('classes/' + this.selected + '/students/' + student.sno, adding ? 'PUT' : 'DELETE');
                student.member = adding;
                this.current.count = this.students.filter(s => s.member).length;
                this.notice = student.name + (adding ? '已加入' : '已移出') + '「' + this.current.name + '」';
            });
        }
    }
};

const EndedExamScores = {
    template: '#ended-exam-scores-template',
    props: { examId: Number },
    data() { return { rows: [], loading: true, error: '', activeReview: null }; },
    mounted() { this.load(); },
    methods: {
        api: teachingApi,
        async load() {
            this.loading = true;
            this.error = '';
            try { this.rows = (await this.api('exams/' + this.examId + '/scores')).students; }
            catch (error) { this.error = error.message; }
            finally { this.loading = false; }
        }
    }
};

const ExamManager = {
    template: '#exam-manager-template',
    components: { EndedExamScores },
    props: { signedIn: Boolean },
    emits: ['close'],
    data() {
        return {
            exams: [], editing: null, editorMode: '', returnFocus: null,
            loginRequired: !this.signedIn, loading: false, error: '', notice: '',
            now: 0, clockOffset: 0, timer: null, openDetails: {}, deletingId: null
        };
    },
    mounted() {
        this.$refs.dialog.focus();
        if (this.loginRequired) return;
        this.refresh();
        this.timer = window.setInterval(() => { this.now = performance.now() + this.clockOffset; }, 1000);
    },
    beforeUnmount() { window.clearInterval(this.timer); },
    methods: {
        trapFocus: trapTeachingFocus,
        api: teachingApi,
        async refresh() {
            this.error = '';
            this.loading = true;
            try {
                const data = await this.api('exams');
                // Compare database wall times on one scale, independent of the browser's time zone.
                this.now = Date.parse(data.server_time + 'Z');
                this.clockOffset = this.now - performance.now();
                this.exams = data.exams;
            } catch (error) {
                this.error = error.message;
            } finally {
                this.loading = false;
            }
        },
        formatTime(value) { return value.replace('T', ' ').slice(0, 16); },
        status(exam) {
            if (this.now < Date.parse(exam.publish_time + 'Z')) return '未开始';
            return this.now < Date.parse(exam.deadline_time + 'Z') ? '进行中' : '已结束';
        },
        async removeExam(exam) {
            if (this.deletingId !== null) return;
            const status = this.status(exam);
            if (status === '已结束') return;
            const running = status === '进行中';
            const impact = running ? '本场已提交的成绩将全部作废，正在考试的学生也将无法交卷。' : '将移除这场考试安排。';
            if (!window.confirm('删除「' + exam.test_name + '」？' + impact)) return;
            this.deletingId = exam.id;
            this.notice = '';
            try {
                await this.api('exams/' + exam.id + '?state=' + (running ? 'running' : 'upcoming'), 'DELETE');
                this.notice = running ? '考试已删除，本场成绩已作废。' : '考试安排已删除。';
            } catch (error) {
                this.notice = error.message;
            } finally {
                await this.refresh();
                this.deletingId = null;
            }
        },
        openEditor(exam, trigger) {
            this.notice = '';
            this.returnFocus = trigger;
            this.editing = exam;
            this.editorMode = exam ? 'edit' : 'create';
        },
        onSaved(message) {
            this.notice = message;
            this.refresh();
        },
        closeEditor() {
            this.editorMode = '';
            this.editing = null;
            this.$nextTick(() => {
                (this.returnFocus?.isConnected ? this.returnFocus : this.$refs.dialog).focus();
            });
        }
    }
};
