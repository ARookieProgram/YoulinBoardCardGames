/** RadioGroupMgr 实际管理的对象是 RadioButton 组件；共享接口里把参数写成了 cc.Node，
 *  这里按运行期真正用到的成员声明（只在本文件可见）。 */
interface RadioButtonLike {
    groupId: number;
    check(value: boolean): void;
}

/** `_groups` 的运行时结构：groupId → 该组的按钮数组；`del` 里会把空组整个 delete 掉。 */
interface RadioGroupMap {
    [groupId: number]: RadioButtonLike[] | undefined;
}

cc.Class({
    extends: cc.Component,

    properties: {
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
        _groups:null as RadioGroupMap | null
    },

    // use this for initialization
    init: function () {
        this._groups = {};
    },
    
    add:function(radioButton: RadioButtonLike){
        var groupId = radioButton.groupId; 
        var buttons = this._groups![groupId];
        if(buttons == null){
            buttons = [];
            this._groups![groupId] = buttons; 
        }
        buttons.push(radioButton);
    },
    
    del:function(radioButton: RadioButtonLike){
        var groupId = radioButton.groupId;
        var buttons = this._groups![groupId];
        if(buttons == null){
            return; 
        }
        var idx = buttons.indexOf(radioButton);
        if(idx != -1){
            buttons.splice(idx,1);            
        }
        if(buttons.length == 0){
            delete this._groups![groupId]   
        }
    },
    
    check:function(radioButton: RadioButtonLike){
        var groupId = radioButton.groupId;
        var buttons = this._groups![groupId];
        if(buttons == null){
            return; 
        }
        for(var i = 0; i < buttons.length; ++i){
            var btn = buttons[i];
            if(btn == radioButton){
                btn.check(true);
            }else{
                btn.check(false);
            }
        }        
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});
export { };
